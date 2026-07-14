"""R2 retrieve — run each unresolved RQ's strategy connectors, collect metadata-
only SourceHits, dedup by canonical-URL hash (design §4.1). On a loop, only
unresolved RQs are re-queried. Query text is the RQ itself in v1 (LLM query
refinement is a later tuning step); connectors do the actual searching.
"""

from app.normalize import canonicalize_url, item_doc_id
from app.research import events
from app.research.context import RunContext
from app.research.schemas import Phase, StrategyQuery


def run(ctx: RunContext) -> None:
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
            if not ctx.budget.can_afford(Phase.R2):
                return
            q = StrategyQuery(rqId=rq.id, query=rq.q, connector=conn_name,
                              language=run.canonicalLanguage, maxResults=8)
            hits = conn.search(q)
            events.connector_search(run.id, Phase.R2.value, conn_name, rq.q, len(hits))
            for h in hits:
                key = item_doc_id(canonicalize_url(h.url))
                ctx.hit_rqs.setdefault(key, set()).add(rq.id)
                if key not in ctx.hit_index:
                    h.connector = h.connector or conn_name
                    ctx.hit_index[key] = h
