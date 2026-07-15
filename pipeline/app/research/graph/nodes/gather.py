"""gather — dispatch / search workers / triage barrier (design §4.1, M2 fan-out).

M1 delegated to phases/gather.py; M2 absorbed that module here and fanned the
retrieval leg out: one worker per (unresolved RQ × enabled connector), running in
parallel under `research_max_concurrency`. Triage stays a barrier on purpose — it
is a quality gate that must rank ALL candidates against each other, so it cannot
start until every search worker has merged its hits.

Event contract (admin flow view): the dispatch emits the single phase_start, the
triage barrier the single phase_end; workers emit no phase events at all — only
their connector_search / llm_call rows, exactly as the sequential code did.
"""

from langgraph.runtime import Runtime
from langgraph.types import Command, Send
from pydantic import BaseModel

from app.config import get_settings
from app.normalize import canonicalize_url, item_doc_id, title_norm_hash
from app.research import events, llm
from app.research.graph.context import ResearchRuntimeContext
from app.research.graph.nodes.common import afford, budget_snapshot
from app.research.graph.state import GatherTask, ResearchState
from app.research.prompts import (
    PROMPT_VERSION,
    RETRIEVE_SYSTEM,
    RETRIEVE_USER,
    TRIAGE_SYSTEM,
    TRIAGE_USER,
)
from app.research.schemas import Phase, StrategyQuery

MAX_SELECTED = 20
MAX_REFINED_QUERIES = 2


class RefinedQuery(BaseModel):
    query: str
    language: str = "ja"


class RefinedQueries(BaseModel):
    queries: list[RefinedQuery] = []


# -- dispatch ------------------------------------------------------------------

def gather_dispatch(state: ResearchState, runtime: Runtime[ResearchRuntimeContext]) -> Command:
    """Fan out one search worker per unresolved RQ × enabled connector."""
    if not afford(state, runtime.context, Phase.gather):
        return Command(goto="budget_stop", update=budget_snapshot(runtime.context))
    run = state["run"]
    events.phase_start(run.id, Phase.gather.value)

    tasks = []
    for rq in (run.plan.rqs if run.plan else []):
        if rq.resolved:
            continue  # a loop re-queries only what coverage left unresolved
        for conn_name in rq.strategies:
            conn = runtime.context.registry.get(conn_name)
            if conn is None or getattr(conn, "disabled", False):
                continue
            tasks.append(Send("gather_search", GatherTask(
                rq_id=rq.id, rq_q=rq.q, connector=conn_name,
                language=run.canonicalLanguage, loop=run.loops)))
    if not tasks:
        return Command(goto="gather_triage")
    return Command(goto=tasks)


# -- worker ---------------------------------------------------------------------

def _refine_queries(task: GatherTask, runtime_ctx: ResearchRuntimeContext) -> list[RefinedQuery]:
    """LLM query refinement per RQ×connector. Any failure (validation, empty
    output) degrades to the raw RQ text — never aborts the phase."""
    try:
        out: RefinedQueries = llm.structured(
            RefinedQueries, get_settings().research_fast_model, RETRIEVE_SYSTEM,
            RETRIEVE_USER.format(rq=task["rq_q"], connector=task["connector"],
                                 language=task["language"],
                                 n=MAX_REFINED_QUERIES),
            budget=runtime_ctx.budget, run_id=runtime_ctx.run_id,
            phase=Phase.gather.value, actor="retriever",
            prompt_version=PROMPT_VERSION)
        queries = [q for q in out.queries if q.query.strip()][:MAX_REFINED_QUERIES]
    except llm.ResearchLLMError:
        queries = []
    if not queries:
        events.fallback(runtime_ctx.run_id, Phase.gather.value, "retriever",
                        {"reason": "query_refinement_failed", "rqId": task["rq_id"],
                         "connector": task["connector"]})
        queries = [RefinedQuery(query=task["rq_q"], language=task["language"])]
    return queries


def gather_search(task: GatherTask, runtime: Runtime[ResearchRuntimeContext]) -> dict:
    """One RQ × one connector. Returns partial hit maps; the channel reducers do
    the cross-worker merge (first hit per urlHash wins; RQ sets union)."""
    ctx = runtime.context
    # Per-worker floor check (the sequential loop broke out mid-phase as the
    # budget drained; residual overspend is bounded by max_concurrency × 1 call).
    if not ctx.budget.can_afford(Phase.gather):
        return {}
    conn = ctx.registry.get(task["connector"])
    if conn is None or getattr(conn, "disabled", False):
        return {}

    hit_index: dict = {}
    hit_rqs: dict[str, set] = {}
    for refined in _refine_queries(task, ctx):
        q = StrategyQuery(rqId=task["rq_id"], query=refined.query,
                          connector=task["connector"], language=refined.language,
                          maxResults=8)
        hits = conn.search(q)
        events.connector_search(ctx.run_id, Phase.gather.value, task["connector"],
                                q.query, len(hits))
        for h in hits:
            key = item_doc_id(canonicalize_url(h.url))
            hit_rqs.setdefault(key, set()).add(task["rq_id"])
            if key not in hit_index:
                h.connector = h.connector or task["connector"]
                hit_index[key] = h
    return {"hit_index": hit_index,
            "hit_rqs": {k: sorted(v) for k, v in hit_rqs.items()},
            "budget": ctx.budget.snapshot()}


# -- triage barrier ---------------------------------------------------------------

class _Selection(BaseModel):
    index: int
    keep: bool = True
    tier: str = "secondary"
    relevance: float = 0.0
    rationale: str = ""


class TriageOut(BaseModel):
    selections: list[_Selection] = []


def _dedup_titles(hits: list) -> list:
    seen: set[str] = set()
    out = []
    for h in hits:
        k = title_norm_hash(h.title)
        if k in seen:
            continue
        seen.add(k)
        out.append(h)
    return out


def gather_triage(state: ResearchState, runtime: Runtime[ResearchRuntimeContext]) -> Command:
    """Rank/tier ALL candidates together, drop tertiary, cap the selection."""
    run = state["run"]
    candidates = _dedup_titles(list((state.get("hit_index") or {}).values()))
    if not candidates:
        events.phase_end(run.id, Phase.gather.value)
        return Command(goto="extract_dispatch",
                       update={"selected": [], **budget_snapshot(runtime.context)})

    rendered = "\n".join(
        f"[{i}] {h.title} | {h.sourceType} | {h.connector} | {h.snippet[:120]}"
        for i, h in enumerate(candidates))
    out: TriageOut = llm.structured(
        TriageOut, get_settings().research_fast_model, TRIAGE_SYSTEM,
        TRIAGE_USER.format(rq=run.theme, candidates=rendered,
                           n=min(len(candidates), MAX_SELECTED)),
        budget=runtime.context.budget, run_id=run.id, phase=Phase.gather.value,
        actor="triage", prompt_version=PROMPT_VERSION)

    kept = []
    for sel in out.selections:
        if 0 <= sel.index < len(candidates) and sel.keep and sel.tier != "tertiary":
            h = candidates[sel.index]
            h.tierHint = sel.tier
            kept.append(h)
    selected = kept[:MAX_SELECTED] or candidates[:5]
    events.phase_end(run.id, Phase.gather.value)
    return Command(goto="extract_dispatch",
                   update={"selected": selected, **budget_snapshot(runtime.context)})
