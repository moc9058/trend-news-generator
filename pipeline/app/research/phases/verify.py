"""verify — claim verification + deterministic coverage assessment (design §4.1).

Verification leg: turn evidence into Claims per RQ: verdict, stance, confidence.
The citation gate and render mode are applied deterministically (rubric), not
left to the LLM. For contested runs, claims carry the contested flag so write
renders ≥2 positions side by side (争点 protocol, design §4.2).

Coverage leg: counts evidence and tier distribution per RQ, marks each
resolved/unresolved, and decides loop vs finalize via the PURE
state.gap_decision (respecting loop cap + budget). Keeping this deterministic
makes the stop condition reproducible and testable; the harness loops back to
gather when the decision is "loop".
"""

from collections import Counter

from pydantic import BaseModel

from app.config import get_settings
from app.repo import research as repo
from app.research import llm, rubric, state
from app.research.context import RunContext
from app.research.prompts import PROMPT_VERSION, VERIFY_SYSTEM, VERIFY_USER
from app.research.schemas import Claim, CoverageReport, Phase, RqCoverage

MIN_EVIDENCE_PER_RQ = 2


class VerifyOut(BaseModel):
    claims: list[Claim] = []


def _tier_mix(evidence: list) -> dict:
    mix: dict[str, int] = {}
    for e in evidence:
        mix[e.tier] = mix.get(e.tier, 0) + 1
    return mix


def run(ctx: RunContext) -> None:
    evidence = repo.get_evidence(ctx.run.id)
    _verify_claims(ctx, evidence)
    _assess_coverage(ctx, evidence)


# -- verification leg ---------------------------------------------------------

def _verify_claims(ctx: RunContext, evidence: list) -> None:
    run = ctx.run
    ev_by_id = {e.evidenceId: e for e in evidence}
    ev_by_rq: dict[str, list] = {}
    for e in evidence:
        for rq in e.rqIds:
            ev_by_rq.setdefault(rq, []).append(e)

    all_claims: list[Claim] = []
    for rq in (run.plan.rqs if run.plan else []):
        evs = ev_by_rq.get(rq.id, [])
        if not evs:
            continue
        rendered = "\n".join(
            f"{e.evidenceId} | {e.tier} | {e.sourceType} | {e.title} | "
            f"claims={e.extraction.claims} | stance={e.extraction.stance}" for e in evs)
        out: VerifyOut = llm.structured(
            VerifyOut, get_settings().research_model, VERIFY_SYSTEM,
            VERIFY_USER.format(rq=rq.q, rq_id=rq.id, evidence=rendered),
            budget=ctx.budget, run_id=run.id, phase=Phase.verify.value,
            actor="verifier", prompt_version=PROMPT_VERSION)
        for c in out.claims:
            backing = [ev_by_id[i] for i in c.evidenceIds if i in ev_by_id]
            gate_ok = rubric.passes_citation_gate(backing)
            c.renderAs = rubric.render_as(c.verdict, c.isInterpretation, gate_ok)
            c.tierMix = _tier_mix(backing)
            if run.plan and run.plan.contested and c.stance:
                c.contested = True
            repo.upsert_claim(run.id, c)
            all_claims.append(c)
    ctx.claims = all_claims


# -- coverage leg (deterministic; drives the gather loop) ----------------------

def _assess_coverage(ctx: RunContext, evidence: list) -> None:
    run = ctx.run
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
        ctx.budget.can_afford(Phase.gather))
    ctx.coverage = coverage
    repo.save(run)  # persists updated rq.resolved flags for a possible loop
