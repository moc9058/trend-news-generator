"""R5 verify — turn evidence into Claims per RQ: verdict, stance, confidence. The
citation gate and render mode are applied deterministically (rubric), not left to
the LLM. For contested runs, claims carry the contested flag so R7 renders ≥2
positions side by side (争点 protocol, design §4.2).
"""

from pydantic import BaseModel

from app.config import get_settings
from app.repo import research as repo
from app.research import llm, rubric
from app.research.context import RunContext
from app.research.prompts import PROMPT_VERSION, VERIFY_SYSTEM, VERIFY_USER
from app.research.schemas import Claim, Phase


class VerifyOut(BaseModel):
    claims: list[Claim] = []


def _tier_mix(evidence: list) -> dict:
    mix: dict[str, int] = {}
    for e in evidence:
        mix[e.tier] = mix.get(e.tier, 0) + 1
    return mix


def run(ctx: RunContext) -> None:
    run = ctx.run
    evidence = repo.get_evidence(run.id)
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
            budget=ctx.budget, run_id=run.id, phase=Phase.R5.value,
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
