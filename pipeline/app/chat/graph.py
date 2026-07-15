"""The chat LangGraph: one graph execution per user message (design doc 11 §5.1).

Two routes out of START:

    chat      : chat_respond ──────────────────────────────────────────► END
    research  : plan_queries → search → select → read ─┬─► synthesize ─► END
                     ▲                                 │
                     └──── gap_check (deep only, ≤1) ◄─┘

No checkpointer. Conversation state is rebuilt from Firestore every turn, because
the admin UI reads those same documents directly — one source of truth beats two.
A single user with one in-flight stream makes mid-graph resume worth little.

Every node opens with `_guard`: cancel, budget, wall-clock. A tripped guard does
not raise — it short-circuits to `synthesize`, which answers from whatever was
gathered (or explains that it could not). Degrading beats erroring: a partial
sourced answer is still useful, and the user already paid for the tokens.

The `hits` reducer is `operator.add` so a gap loop accumulates rather than
replaces; everything else overwrites.
"""

import operator
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Annotated, Callable, Optional, TypedDict

from langgraph.config import get_stream_writer
from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime

from app.chat import prompts
from app.chat.schemas import (
    ChatDepth,
    ChatGapReport,
    ChatMode,
    ChatReading,
    ChatResearchPlan,
    ChatSelection,
    ChatSource,
)
from app.chat.stream_llm import stream_chat
from app.config import get_settings
from app.normalize import canonicalize_url, item_doc_id
from app.research import llm, rubric
from app.research.budget import Budget
from app.research.fetch.extract_text import extract
from app.research.phases.plan import STRATEGY_MATRIX
from app.research.schemas import SourceHit, StrategyQuery
from app.utils.logging import get_logger

log = get_logger(__name__)

# Per-depth shape of a research run (§5.1). quick trades recall for latency.
MAX_QUERIES = {ChatDepth.quick.value: 4, ChatDepth.deep.value: 10}
MAX_SELECT = {ChatDepth.quick.value: 6, ChatDepth.deep.value: 14}
MAX_LOOPS = 1
READING_EXCERPT_CHARS = 6000   # per source, into the synthesize prompt
GAP_EXCERPT_CHARS = 600        # per source, into the cheaper gap prompt

# Connectors chat may plan for: the research registry plus our own collected items.
INTERNAL_CONNECTOR = "internal_items"
VALID_CONNECTORS = set(STRATEGY_MATRIX["society_culture"]) | {"ieee", INTERNAL_CONNECTOR}


class ChatState(TypedDict, total=False):
    thread_id: str
    assistant_message_id: str
    mode: str
    depth: str
    history: list[dict]
    user_input: str
    plan: Optional[dict]
    hits: Annotated[list, operator.add]
    selected: list
    readings: list
    gap: Optional[dict]
    loops: int
    answer: str
    sources: list
    stop_reason: str   # "" | cancelled | budget | deadline


@dataclass
class ChatRunContext:
    """Per-execution resources. Kept out of graph state (they are not
    serialisable and not conversation) and passed via langgraph's Runtime
    context — the same idiom as research's RunContext."""
    settings: object
    budget: Budget
    registry: dict = field(default_factory=dict)
    fetcher: object = None
    cancel_check: Optional[Callable[[], bool]] = None
    deadline: Optional[datetime] = None
    llm_events: list = field(default_factory=list)


# --------------------------------------------------------------------------- #
# Guards                                                                       #
# --------------------------------------------------------------------------- #

def _guard(ctx: ChatRunContext) -> str:
    """Why the run must stop now, or "" to continue."""
    if ctx.cancel_check is not None and ctx.cancel_check():
        return "cancelled"
    if ctx.budget.remaining() <= 0:
        return "budget"
    if ctx.deadline is not None and datetime.now(timezone.utc) > ctx.deadline:
        return "deadline"
    return ""


def _emit(kind: str, data: dict) -> None:
    """Push a progress/token event to the SSE layer. Outside a graph run (unit
    tests calling a node directly) there is no writer, so this is a no-op."""
    try:
        writer = get_stream_writer()
    except Exception:  # noqa: BLE001 — not inside a graph execution
        return
    if writer is not None:
        writer({"type": kind, "data": data})


def _status(stage: str, **detail) -> None:
    _emit("status", {"stage": stage, **detail})


# --------------------------------------------------------------------------- #
# Nodes                                                                        #
# --------------------------------------------------------------------------- #

def chat_respond(state: ChatState, runtime: Runtime[ChatRunContext]) -> ChatState:
    """Sparring mode: no tools, just the conversation and a pointed interlocutor."""
    ctx = runtime.context
    messages = [*state.get("history", []), {"role": "user", "content": state["user_input"]}]
    text, _usage = stream_chat(
        model=ctx.settings.chat_model, system=prompts.SPARRING_SYSTEM,
        messages=messages, budget=ctx.budget,
        on_delta=lambda d: _emit("token", {"delta": d}),
        actor="sparring", phase=ChatMode.chat.value, events=ctx.llm_events,
        should_stop=ctx.cancel_check,
    )
    stop = "cancelled" if (ctx.cancel_check and ctx.cancel_check()) else ""
    return {"answer": text, "sources": [], "stop_reason": stop}


def plan_queries(state: ChatState, runtime: Runtime[ChatRunContext]) -> ChatState:
    ctx = runtime.context
    stop = _guard(ctx)
    if stop:
        return {"stop_reason": stop}
    _status("planning")

    depth = state.get("depth", ChatDepth.quick.value)
    gap = state.get("gap") or {}
    followups = gap.get("followupQueries") or []
    if followups:
        # Gap loop: the gap critic already named the queries; re-planning from
        # scratch would only re-propose what we just searched.
        plan = {"themeClass": (state.get("plan") or {}).get("themeClass", "society_culture"),
                "queries": followups, "rationale": "gap follow-up"}
        return {"plan": plan, "loops": state.get("loops", 0) + 1}

    history = _history_block(state)
    result: ChatResearchPlan = llm.structured(
        ChatResearchPlan, ctx.settings.chat_fast_model, prompts.PLAN_SYSTEM,
        prompts.PLAN_USER.format(history=history, question=state["user_input"],
                                 max_queries=MAX_QUERIES[depth]),
        budget=ctx.budget, run_id=state["thread_id"], phase="research",
        actor="planner", prompt_version=prompts.PROMPT_VERSION,
        event_sink=ctx.llm_events.append)

    queries = [q for q in result.queries if q.connector in VALID_CONNECTORS]
    if not queries:
        # The planner named only unknown connectors (or none). Fall back to the
        # theme's matrix order rather than searching nothing.
        matrix = STRATEGY_MATRIX.get(result.themeClass, STRATEGY_MATRIX["society_culture"])
        queries = [ChatQueryShim(query=state["user_input"], connector=c)
                   for c in matrix[:2]]
    plan = {"themeClass": result.themeClass,
            "queries": [q.model_dump() if hasattr(q, "model_dump") else dict(q)
                        for q in queries[:MAX_QUERIES[depth]]],
            "rationale": result.rationale}
    return {"plan": plan, "loops": state.get("loops", 0)}


class ChatQueryShim:
    """Minimal stand-in when the planner returns no usable connector."""

    def __init__(self, query: str, connector: str, language: str = "ja"):
        self.query, self.connector, self.language = query, connector, language

    def model_dump(self) -> dict:
        return {"query": self.query, "connector": self.connector, "language": self.language}


def search(state: ChatState, runtime: Runtime[ChatRunContext]) -> ChatState:
    """Run each planned query against its connector, sequentially.

    Sequential on purpose (§4): `Fetcher` and the connector circuit-breakers are
    not thread-safe until the LangGraph migration's M2 adds locking. Parallel
    fan-out is a v2 that unblocks then.
    """
    ctx = runtime.context
    stop = _guard(ctx)
    if stop:
        return {"stop_reason": stop}

    plan = state.get("plan") or {}
    seen = {_hit_key(h) for h in state.get("hits", [])}
    found: list[SourceHit] = []
    for q in plan.get("queries", []):
        if _guard(ctx):
            break
        name = q.get("connector", "")
        _status("searching", connector=name, query=q.get("query", "")[:120])
        try:
            hits = _run_connector(ctx, name, q)
        except Exception as exc:  # noqa: BLE001 — a connector failure is non-fatal
            log.warning("chat connector failed", extra={"fields": {
                "connector": name, "error": str(exc)}})
            continue
        for h in hits:
            key = _hit_key(h)
            if key in seen:
                continue
            seen.add(key)
            found.append(h)
        _status("searching", connector=name, count=len(found))
    return {"hits": found}


def _run_connector(ctx: ChatRunContext, name: str, q: dict) -> list[SourceHit]:
    if name == INTERNAL_CONNECTOR:
        return _search_internal_items(q.get("query", ""))
    connector = ctx.registry.get(name)
    if connector is None:
        return []
    return connector.search(StrategyQuery(
        rqId="chat", query=q.get("query", ""), language=q.get("language", "ja"),
        maxResults=8, connector=name))


def _search_internal_items(query: str) -> list[SourceHit]:
    """Keyword-match this system's own collected items (design doc 11 §5.1).

    Naive token overlap, not relevance ranking: Firestore has no full-text index,
    and these hits are re-scored by the rubric alongside every other source
    anyway. Import is local so the graph module does not pull Firestore at import.
    """
    from app.repo import items as items_repo

    terms = {t for t in _tokens(query) if len(t) > 1}
    if not terms:
        return []
    hits: list[SourceHit] = []
    for item in items_repo.recent_all(hours=24 * 30, limit=200):
        haystack = _tokens(f"{item.title} {item.summary}")
        if not terms & haystack:
            continue
        hits.append(SourceHit(
            title=item.title, url=item.canonicalUrl, snippet=item.summary[:400],
            publishedAt=item.publishedAt.isoformat() if item.publishedAt else None,
            sourceType="quality_news", connector=INTERNAL_CONNECTOR,
            contentText=item.contentText))
    return hits[:8]


def _tokens(text: str) -> set[str]:
    import re
    return set(re.findall(r"[a-z0-9]+|[ぁ-んァ-ヴ一-鿿가-힣]{2,}", text.lower()))


def _hit_key(hit) -> str:
    url = hit.url if isinstance(hit, SourceHit) else hit.get("url", "")
    return item_doc_id(canonicalize_url(url))


def select(state: ChatState, runtime: Runtime[ChatRunContext]) -> ChatState:
    """Rank hits by the shared reliability rubric; deep additionally asks an LLM
    to judge relevance, which the rubric cannot see."""
    ctx = runtime.context
    stop = _guard(ctx)
    if stop:
        return {"stop_reason": stop}
    _status("selecting")

    depth = state.get("depth", ChatDepth.quick.value)
    hits = [h for h in state.get("hits", []) if getattr(h, "url", "")]
    if not hits:
        return {"selected": []}

    scored = []
    for h in hits:
        tier = rubric.classify_tier(h.sourceType, h.tierHint)
        score = rubric.score_reliability(h.sourceType, h.url).score
        scored.append((score, tier, h))
    # Primary first, then reliability. Unlike the report, tertiary is allowed
    # through — chat favours speed and an answer over an airtight citation gate.
    tier_rank = {"primary": 0, "secondary": 1, "tertiary": 2}
    scored.sort(key=lambda t: (tier_rank.get(t[1], 3), -t[0]))
    ordered = [h for _s, _t, h in scored]
    limit = MAX_SELECT[depth]

    if depth == ChatDepth.deep.value and len(ordered) > limit:
        ordered = _llm_select(ctx, state, ordered, limit)
    return {"selected": ordered[:limit]}


def _llm_select(ctx: ChatRunContext, state: ChatState, ordered: list, limit: int) -> list:
    listing = "\n".join(
        f"{i}. [{rubric.classify_tier(h.sourceType, h.tierHint)}"
        f"/{rubric.score_reliability(h.sourceType, h.url).score}] {h.title} — {h.snippet[:160]}"
        for i, h in enumerate(ordered[:40]))
    try:
        result: ChatSelection = llm.structured(
            ChatSelection, ctx.settings.chat_fast_model, prompts.SELECT_SYSTEM,
            prompts.SELECT_USER.format(question=state["user_input"], hits=listing,
                                       max_keep=limit),
            budget=ctx.budget, run_id=state["thread_id"], phase="research",
            actor="selector", prompt_version=prompts.PROMPT_VERSION,
            event_sink=ctx.llm_events.append)
    except Exception as exc:  # noqa: BLE001 — fall back to the rubric ordering
        log.warning("chat select failed; using rubric order",
                    extra={"fields": {"error": str(exc)}})
        return ordered
    keep = [s for s in result.selections if s.keep and 0 <= s.index < len(ordered)]
    keep.sort(key=lambda s: -s.relevance)
    picked = [ordered[s.index] for s in keep]
    return picked or ordered


def read(state: ChatState, runtime: Runtime[ChatRunContext]) -> ChatState:
    """Fetch and extract the selected sources' bodies.

    Reuses research's Fetcher wholesale, so chat inherits its SSRF guard, robots
    handling, ≤1rps per host, and size caps for free. Unlike the report we take no
    GCS snapshot — chat's audit needs are lighter, and the URL and fetch time are
    retained on the message's sources.
    """
    ctx = runtime.context
    stop = _guard(ctx)
    if stop:
        return {"stop_reason": stop}

    existing = list(state.get("readings", []))
    seen = {r.urlHash for r in existing}
    n = len(existing)
    for hit in state.get("selected", []):
        if _guard(ctx) or not ctx.budget.fetch_available():
            break
        url_hash = _hit_key(hit)
        if url_hash in seen:
            continue
        text = _read_one(ctx, hit)
        if not text:
            continue
        seen.add(url_hash)
        n += 1
        existing.append(ChatReading(
            n=n, url=hit.url, title=hit.title,
            tier=rubric.classify_tier(hit.sourceType, hit.tierHint),
            score=rubric.score_reliability(hit.sourceType, hit.url).score,
            connector=hit.connector, text=text, urlHash=url_hash))
        _status("reading", url=hit.url, count=n)
    return {"readings": existing}


def _read_one(ctx: ChatRunContext, hit: SourceHit) -> str:
    # kokkai (and our own items) already carry the full text — no fetch needed,
    # same shortcut as the report's extract phase.
    if hit.contentText:
        return hit.contentText[:READING_EXCERPT_CHARS * 2]
    if ctx.fetcher is None:
        return ""
    _status("reading", url=hit.url)
    try:
        result = ctx.fetcher.fetch(hit.url)
    except Exception as exc:  # noqa: BLE001 — one dead link must not end the run
        log.warning("chat fetch failed", extra={"fields": {"url": hit.url, "error": str(exc)}})
        return ""
    ctx.budget.note_fetch()
    if result is None:
        return ""
    try:
        return extract(result.data, result.mimeType)
    except Exception as exc:  # noqa: BLE001
        log.warning("chat extract failed", extra={"fields": {"url": hit.url, "error": str(exc)}})
        return ""


def gap_check(state: ChatState, runtime: Runtime[ChatRunContext]) -> ChatState:
    """deep only: can we answer yet, or is one more round worth it?"""
    ctx = runtime.context
    stop = _guard(ctx)
    if stop:
        return {"stop_reason": stop}
    _status("gap_check")

    readings = state.get("readings", [])
    if not readings:
        return {"gap": {"decision": "finalize"}}
    listing = "\n".join(f"[{r.n}] {r.title}\n{r.text[:GAP_EXCERPT_CHARS]}" for r in readings)
    try:
        result: ChatGapReport = llm.structured(
            ChatGapReport, ctx.settings.chat_fast_model, prompts.GAP_SYSTEM,
            prompts.GAP_USER.format(question=state["user_input"], readings=listing),
            budget=ctx.budget, run_id=state["thread_id"], phase="research",
            actor="gap", prompt_version=prompts.PROMPT_VERSION,
            event_sink=ctx.llm_events.append)
    except Exception as exc:  # noqa: BLE001 — a failed gap check just means finalize
        log.warning("chat gap check failed", extra={"fields": {"error": str(exc)}})
        return {"gap": {"decision": "finalize"}}
    return {"gap": result.model_dump()}


def synthesize(state: ChatState, runtime: Runtime[ChatRunContext]) -> ChatState:
    """Stream the cited answer. Also the landing point for every short-circuit,
    so it must cope with zero readings."""
    ctx = runtime.context
    readings = state.get("readings", [])
    sources = [r.to_source() for r in readings]
    _emit("sources", {"sources": [s.model_dump() for s in sources]})
    _status("synthesizing")

    depth = state.get("depth", ChatDepth.quick.value)
    model = (ctx.settings.chat_model if depth == ChatDepth.deep.value
             else ctx.settings.chat_research_model)
    stop = state.get("stop_reason", "")

    if not readings:
        note = _degraded_note(stop, empty=True)
        text, _u = stream_chat(
            model=model, system=prompts.SPARRING_SYSTEM,
            messages=[*state.get("history", []),
                      {"role": "user", "content": state["user_input"]},
                      {"role": "system", "content": note}],
            budget=ctx.budget, on_delta=lambda d: _emit("token", {"delta": d}),
            actor="synthesizer", phase="research", events=ctx.llm_events)
        return {"answer": text, "sources": []}

    listing = "\n\n".join(
        f"[{r.n}] {r.title} ({r.url}) — tier={r.tier}, reliability={r.score}\n"
        f"{r.text[:READING_EXCERPT_CHARS]}" for r in readings)
    text, _u = stream_chat(
        model=model, system=prompts.SYNTH_SYSTEM,
        messages=[*state.get("history", []), {"role": "user", "content":
                  prompts.SYNTH_USER.format(question=state["user_input"], readings=listing,
                                            degraded_note=_degraded_note(stop))}],
        budget=ctx.budget, on_delta=lambda d: _emit("token", {"delta": d}),
        actor="synthesizer", phase="research", events=ctx.llm_events,
        should_stop=ctx.cancel_check)
    return {"answer": text, "sources": sources}


def _degraded_note(stop: str, empty: bool = False) -> str:
    if empty:
        base = ("The source search returned nothing usable, so no citations are "
                "available. Tell the user plainly that you could not find sources, "
                "then answer from your own knowledge if you can — labelling it "
                "explicitly as unsourced.")
        return base + _stop_clause(stop)
    if not stop:
        return ""
    return ("NOTE: the investigation was cut short" + _stop_clause(stop) +
            " Answer with the sources gathered so far and state that the search "
            "was incomplete.\n\n")


def _stop_clause(stop: str) -> str:
    return {
        "cancelled": " because the user cancelled it.",
        "budget": " because it reached its cost limit.",
        "deadline": " because it reached its time limit.",
    }.get(stop, "")


def _history_block(state: ChatState) -> str:
    return "\n".join(f"{m['role']}: {m['content'][:500]}"
                     for m in state.get("history", [])) or "(none)"


# --------------------------------------------------------------------------- #
# Wiring                                                                       #
# --------------------------------------------------------------------------- #

def _route_mode(state: ChatState) -> str:
    return ("chat_respond" if state.get("mode") == ChatMode.chat.value
            else "plan_queries")


def _after(node_ok: str) -> Callable[[ChatState], str]:
    """A tripped guard skips the rest of the pipeline and goes straight to the
    answer, rather than running the remaining nodes as no-ops."""
    def _route(state: ChatState) -> str:
        return "synthesize" if state.get("stop_reason") else node_ok
    return _route


def _after_read(state: ChatState) -> str:
    if state.get("stop_reason"):
        return "synthesize"
    if (state.get("depth") == ChatDepth.deep.value
            and state.get("loops", 0) < MAX_LOOPS):
        return "gap_check"
    return "synthesize"


def _after_gap(state: ChatState) -> str:
    if state.get("stop_reason"):
        return "synthesize"
    gap = state.get("gap") or {}
    if (gap.get("decision") == "loop" and state.get("loops", 0) < MAX_LOOPS
            and gap.get("followupQueries")):
        return "plan_queries"
    return "synthesize"


def build_graph():
    g = StateGraph(ChatState, context_schema=ChatRunContext)
    g.add_node("chat_respond", chat_respond)
    g.add_node("plan_queries", plan_queries)
    g.add_node("search", search)
    g.add_node("select", select)
    g.add_node("read", read)
    g.add_node("gap_check", gap_check)
    g.add_node("synthesize", synthesize)

    g.add_conditional_edges(START, _route_mode, ["chat_respond", "plan_queries"])
    g.add_edge("chat_respond", END)
    g.add_conditional_edges("plan_queries", _after("search"), ["search", "synthesize"])
    g.add_conditional_edges("search", _after("select"), ["select", "synthesize"])
    g.add_conditional_edges("select", _after("read"), ["read", "synthesize"])
    g.add_conditional_edges("read", _after_read, ["gap_check", "synthesize"])
    g.add_conditional_edges("gap_check", _after_gap, ["plan_queries", "synthesize"])
    g.add_edge("synthesize", END)
    return g.compile()


def make_context(*, depth: str, cancel_check: Optional[Callable[[], bool]] = None,
                 registry: Optional[dict] = None, fetcher=None,
                 now: Optional[datetime] = None) -> ChatRunContext:
    """Assemble a run's resources: per-depth budget, fetch cap and deadline."""
    from datetime import timedelta

    from app.research.schemas import BudgetState

    settings = get_settings()
    deep = depth == ChatDepth.deep.value
    budget = Budget(BudgetState(
        usdCap=settings.chat_budget_deep_usd if deep else settings.chat_budget_quick_usd,
        fetchCap=settings.chat_max_fetches_deep if deep else settings.chat_max_fetches_quick))
    minutes = (settings.chat_wall_clock_deep_min if deep
               else settings.chat_wall_clock_quick_min)
    return ChatRunContext(
        settings=settings, budget=budget, registry=registry or {}, fetcher=fetcher,
        cancel_check=cancel_check,
        deadline=(now or datetime.now(timezone.utc)) + timedelta(minutes=minutes))
