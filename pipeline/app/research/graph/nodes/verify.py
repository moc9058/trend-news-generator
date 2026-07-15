"""verify — dispatch / per-RQ workers / coverage barrier (design §4.1, M2).

M2 absorbed phases/verify.py. Verification fans out one worker per RQ that has
evidence; coverage stays a barrier because it is the quality gate that judges ALL
RQs together and drives the gather loop — the branch itself is still the pure
state.gap_decision, never an LLM.

Workers append their claims to the `claims_buf` accumulator, which the dispatch
RESETs first: without the reset, a loop's second verify pass would append onto
the first pass's claims and duplicate everything (the sequential code overwrote
ctx.claims wholesale each pass — RESET + rebuild reproduces that).
"""

from collections import Counter

from langgraph.runtime import Runtime
from langgraph.types import Command, Send
from pydantic import BaseModel

from app.config import get_settings
from app.repo import research as repo
from app.research import events, llm, rubric, state as pure_state
from app.research.graph.context import ResearchRuntimeContext
from app.research.graph.nodes.common import afford, budget_snapshot
from app.research.graph.state import RESET, ResearchState, VerifyTask
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


# -- dispatch ------------------------------------------------------------------

def verify_dispatch(state: ResearchState, runtime: Runtime[ResearchRuntimeContext]) -> Command:
    if not afford(state, runtime.context, Phase.verify):
        return Command(goto="budget_stop", update=budget_snapshot(runtime.context))
    run = state["run"]
    events.phase_start(run.id, Phase.verify.value)

    evidence = repo.get_evidence(run.id)
    with_evidence = {rq_id for e in evidence for rq_id in e.rqIds}
    contested = bool(run.plan and run.plan.contested)
    tasks = [Send("verify_rq", VerifyTask(rq_id=rq.id, rq_q=rq.q, contested=contested))
             for rq in (run.plan.rqs if run.plan else [])
             if rq.id in with_evidence]
    if not tasks:
        return Command(goto="coverage", update={"claims_buf": RESET})
    return Command(goto=tasks, update={"claims_buf": RESET})


# -- worker ---------------------------------------------------------------------

def verify_rq(task: VerifyTask, runtime: Runtime[ResearchRuntimeContext]) -> dict:
    """Turn one RQ's evidence into gated Claims.

    Reads evidence back from Firestore rather than hauling it in the payload —
    it is durable there, and a Send's arg is checkpointed with the superstep.
    The citation gate / renderAs stay deterministic (rubric), exactly as before.

    Concurrency note: google-cloud-firestore's Client is documented safe for
    concurrent use except for Transaction/WriteBatch objects shared across
    threads. Workers only do plain document reads, `set()`s and `.add()`s; the
    one transaction in this repo (claim_next's lease CAS) runs before the graph,
    single-threaded.
    """
    ctx = runtime.context
    if not ctx.budget.can_afford(Phase.verify):
        return {}
    evidence = repo.get_evidence(ctx.run_id)
    ev_by_id = {e.evidenceId: e for e in evidence}
    evs = [e for e in evidence if task["rq_id"] in e.rqIds]
    if not evs:
        return {}

    rendered = "\n".join(
        f"{e.evidenceId} | {e.tier} | {e.sourceType} | {e.title} | "
        f"claims={e.extraction.claims} | stance={e.extraction.stance}" for e in evs)
    out: VerifyOut = llm.structured(
        VerifyOut, get_settings().research_model, VERIFY_SYSTEM,
        VERIFY_USER.format(rq=task["rq_q"], rq_id=task["rq_id"], evidence=rendered),
        budget=ctx.budget, run_id=ctx.run_id, phase=Phase.verify.value,
        actor="verifier", prompt_version=PROMPT_VERSION)

    claims: list[Claim] = []
    for c in out.claims:
        backing = [ev_by_id[i] for i in c.evidenceIds if i in ev_by_id]
        gate_ok = rubric.passes_citation_gate(backing)
        c.renderAs = rubric.render_as(c.verdict, c.isInterpretation, gate_ok)
        c.tierMix = _tier_mix(backing)
        if task["contested"] and c.stance:
            c.contested = True
        repo.upsert_claim(ctx.run_id, c)
        claims.append(c)
    return {"claims_buf": claims, "budget": ctx.budget.snapshot()}


# -- coverage barrier -------------------------------------------------------------

def coverage(state: ResearchState, runtime: Runtime[ResearchRuntimeContext]) -> Command:
    """Deterministic coverage over ALL RQs; decides loop vs finalize.

    THE ONLY PLACE `loops` IS INCREMENTED.
    """
    run = state["run"]
    budget = runtime.context.budget

    # claims_buf -> claims, deduped by claimId (an LLM may re-mint an id; last wins)
    deduped: dict[str, Claim] = {}
    for c in state.get("claims_buf") or []:
        deduped[c.claimId] = c
    claims = list(deduped.values())

    evidence = repo.get_evidence(run.id)
    per_rq: dict[str, list] = {}
    for e in evidence:
        for rq_id in e.rqIds:
            per_rq.setdefault(rq_id, []).append(e)

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

    report = CoverageReport(loops=run.loops, rqCoverage=rqcov,
                            budgetRemaining=budget.remaining())
    report.decision = pure_state.gap_decision(
        report, run.loops, get_settings().research_max_loops,
        budget.can_afford(Phase.gather))
    repo.save(run)  # persists updated rq.resolved flags for a possible loop

    events.phase_end(run.id, Phase.verify.value)
    update = {"run": run, "claims": claims, "coverage": report,
              **budget_snapshot(runtime.context)}
    if report.decision == "loop":
        run.loops += 1
        repo.update_fields(run.id, {"loops": run.loops})
        return Command(goto="gather_dispatch", update=update)
    return Command(goto="write_canonical", update=update)
