"""R6 gap — deterministic coverage assessment (design §4.1). Counts evidence and
tier distribution per RQ, marks each resolved/unresolved, and decides loop vs
finalize via the PURE state.gap_decision (respecting loop cap + budget). Keeping
this deterministic makes the stop condition reproducible and testable.
"""

from collections import Counter

from app.config import get_settings
from app.repo import research as repo
from app.research import state
from app.research.context import RunContext
from app.research.schemas import CoverageReport, Phase, RqCoverage

MIN_EVIDENCE_PER_RQ = 2


def run(ctx: RunContext) -> None:
    run = ctx.run
    evidence = repo.get_evidence(run.id)
    per_rq: dict[str, list] = {}
    for e in evidence:
        for rq in e.rqIds:
            per_rq.setdefault(rq, []).append(e)

    rqcov: list[RqCoverage] = []
    for rq in (run.plan.rqs if run.plan else []):
        evs = per_rq.get(rq.id, [])
        tiers = Counter(e.tier for e in evs)
        resolved = (len(evs) >= MIN_EVIDENCE_PER_RQ
                    and (tiers.get("primary", 0) + tiers.get("secondary", 0)) >= 1)
        rq.resolved = resolved
        rqcov.append(RqCoverage(
            rqId=rq.id, evidence=len(evs), tiers=dict(tiers), resolved=resolved,
            gap="" if resolved else "insufficient tiered evidence"))

    coverage = CoverageReport(loops=run.loops, rqCoverage=rqcov,
                              budgetRemaining=ctx.budget.remaining())
    coverage.decision = state.gap_decision(
        coverage, run.loops, get_settings().research_max_loops,
        ctx.budget.can_afford(Phase.R2))
    ctx.coverage = coverage
    repo.save(run)  # persists updated rq.resolved flags for a possible loop
