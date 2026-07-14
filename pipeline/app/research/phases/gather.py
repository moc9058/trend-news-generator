"""gather — retrieval + triage in one phase (design §4.1).

Retrieval leg: for each unresolved RQ, an LLM first refines the RQ into focused
per-connector search queries (falling back to the raw RQ text if refinement
fails — refinement must never fail the phase), then the strategy connectors run
and the metadata-only SourceHits are deduped by canonical-URL hash. On a loop,
only unresolved RQs are re-queried.

Triage leg: near-duplicate title dedup (reuses normalize.title_norm_hash), then
an LLM ranks/tiers the candidates. Tertiary hits are dropped (navigation only,
never cited — design §4.2). Selection is capped to keep extract cost bounded.
"""

from pydantic import BaseModel

from app.config import get_settings
from app.normalize import canonicalize_url, item_doc_id, title_norm_hash
from app.research import events, llm
from app.research.context import RunContext
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


def run(ctx: RunContext) -> None:
    _retrieve(ctx)
    _triage(ctx)


# -- retrieval leg -----------------------------------------------------------

def _refine_queries(ctx: RunContext, rq, conn_name: str) -> list[RefinedQuery]:
    """LLM query refinement per RQ×connector. Any failure (validation, empty
    output) degrades to the raw RQ text — never aborts the phase."""
    run = ctx.run
    try:
        out: RefinedQueries = llm.structured(
            RefinedQueries, get_settings().research_fast_model, RETRIEVE_SYSTEM,
            RETRIEVE_USER.format(rq=rq.q, connector=conn_name,
                                 language=run.canonicalLanguage,
                                 n=MAX_REFINED_QUERIES),
            budget=ctx.budget, run_id=run.id, phase=Phase.gather.value,
            actor="retriever", prompt_version=PROMPT_VERSION)
        queries = [q for q in out.queries if q.query.strip()][:MAX_REFINED_QUERIES]
    except llm.ResearchLLMError:
        queries = []
    if not queries:
        events.fallback(run.id, Phase.gather.value, "retriever",
                        {"reason": "query_refinement_failed", "rqId": rq.id,
                         "connector": conn_name})
        queries = [RefinedQuery(query=rq.q, language=run.canonicalLanguage)]
    return queries


def _retrieve(ctx: RunContext) -> None:
    run = ctx.run
    plan = run.plan
    if plan is None:
        return
    for rq in plan.rqs:
        if rq.resolved:
            continue
        for conn_name in rq.strategies:
            conn = ctx.registry.get(conn_name)
            if conn is None or getattr(conn, "disabled", False):
                continue
            if not ctx.budget.can_afford(Phase.gather):
                return
            for refined in _refine_queries(ctx, rq, conn_name):
                q = StrategyQuery(rqId=rq.id, query=refined.query,
                                  connector=conn_name, language=refined.language,
                                  maxResults=8)
                hits = conn.search(q)
                events.connector_search(run.id, Phase.gather.value, conn_name,
                                        q.query, len(hits))
                for h in hits:
                    key = item_doc_id(canonicalize_url(h.url))
                    ctx.hit_rqs.setdefault(key, set()).add(rq.id)
                    if key not in ctx.hit_index:
                        h.connector = h.connector or conn_name
                        ctx.hit_index[key] = h


# -- triage leg ---------------------------------------------------------------

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


def _triage(ctx: RunContext) -> None:
    candidates = _dedup_titles(ctx.hits)
    if not candidates:
        ctx.selected = []
        return
    rendered = "\n".join(
        f"[{i}] {h.title} | {h.sourceType} | {h.connector} | {h.snippet[:120]}"
        for i, h in enumerate(candidates))
    out: TriageOut = llm.structured(
        TriageOut, get_settings().research_fast_model, TRIAGE_SYSTEM,
        TRIAGE_USER.format(rq=ctx.run.theme, candidates=rendered,
                           n=min(len(candidates), MAX_SELECTED)),
        budget=ctx.budget, run_id=ctx.run.id, phase=Phase.gather.value,
        actor="triage", prompt_version=PROMPT_VERSION)

    kept = []
    for sel in out.selections:
        if 0 <= sel.index < len(candidates) and sel.keep and sel.tier != "tertiary":
            h = candidates[sel.index]
            h.tierHint = sel.tier
            kept.append(h)
    ctx.selected = kept[:MAX_SELECTED] or candidates[:5]
