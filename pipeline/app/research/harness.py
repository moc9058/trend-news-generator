"""ResearchHarness — the deterministic phase-transition loop (design §3.1, §4.1).

The harness carries NO judgement: it only decides which phase runs next, whether
to loop, whether the budget allows continuing, and when to stop — all via the pure
functions in state.py / budget.py. LLM judgement lives entirely inside the phases.
At every phase boundary it persists state + heartbeat (crash → resume from the last
completed phase) and honours a cancel request.
"""

from typing import Callable, Optional

from app.repo import research as repo
from app.research import events, state
from app.research.budget import Budget
from app.research.context import RunContext
from app.research.phases import extract, gather, plan, review, verify, write
from app.research.schemas import Phase, ResearchRunStatus
from app.utils.logging import get_logger

log = get_logger(__name__)

PHASE_FN: dict[Phase, Callable[[RunContext], None]] = {
    Phase.plan: plan.run, Phase.gather: gather.run, Phase.extract: extract.run,
    Phase.verify: verify.run, Phase.write: write.run, Phase.review: review.run,
}


class ResearchHarness:
    def __init__(self, ctx_factory: Optional[Callable[[object], RunContext]] = None):
        # ctx_factory is a test seam for injecting a fake registry / fetcher.
        self._ctx_factory = ctx_factory

    def run(self, run_id: str) -> Optional[RunContext]:
        run = repo.get(run_id)
        if run is None or state.is_terminal(run.status):
            return None
        ctx = self._make_ctx(run)
        phase = Phase(run.phase)

        while True:
            if self._cancelled(run_id):
                repo.set_status(run_id, ResearchRunStatus.cancelled.value)
                log.info("research run cancelled", extra={"fields": {"run": run_id}})
                return ctx
            if not ctx.budget.can_afford(phase):
                events.budget_check(run_id, phase.value, ctx.budget.remaining(), ok=False)
                self._graceful_stop(ctx, phase)
                return ctx

            events.phase_start(run_id, phase.value)
            fn = PHASE_FN.get(phase)
            if fn is not None:
                fn(ctx)
            events.phase_end(run_id, phase.value)

            run.budget = ctx.budget.state  # same object; charges applied in place
            repo.update_fields(run_id, {"budget": run.budget.model_dump(),
                                        "phase": phase.value})
            repo.heartbeat(run_id)

            # optional plan-approval gate after plan (design §4.1): pause for admin
            # sign-off, resuming at gather once approve-plan re-queues the run.
            if phase == Phase.plan and run.planApproval and not run.planApproved:
                run.phase = Phase.gather.value
                repo.set_status(run_id, ResearchRunStatus.awaiting_plan_approval.value,
                                phase=Phase.gather.value)
                log.info("research run awaiting plan approval", extra={"fields": {"run": run_id}})
                return ctx

            nxt = self._next_phase(phase, ctx)
            if nxt is None:
                break
            phase = nxt
            run.phase = phase.value

        return ctx

    # -- transition logic (deterministic) -------------------------------------
    def _next_phase(self, phase: Phase, ctx: RunContext) -> Optional[Phase]:
        if phase == Phase.verify:
            if ctx.coverage and ctx.coverage.decision == "loop":
                ctx.run.loops += 1
                repo.update_fields(ctx.run.id, {"loops": ctx.run.loops})
                return Phase.gather  # re-retrieve only the unresolved RQs (§4.1)
            return Phase.write
        if phase == Phase.review:
            # review.run stored the critic decision and already ran handoff on
            # "proceed" — the harness only honours the revise loop-back here.
            if ctx.review_decision == "revise":
                ctx.revisions += 1
                return Phase.write  # one corrective rewrite (§4.1)
            return None
        return state.linear_next(phase)

    # -- helpers --------------------------------------------------------------
    def _make_ctx(self, run) -> RunContext:
        if self._ctx_factory is not None:
            return self._ctx_factory(run)
        from app.research.fetch.fetcher import Fetcher
        from app.research.sources.base import build_registry
        return RunContext(run=run, budget=Budget(run.budget),
                          registry=build_registry(), fetcher=Fetcher())

    def _cancelled(self, run_id: str) -> bool:
        cur = repo.get(run_id)
        return bool(cur and cur.cancelRequested)

    def _graceful_stop(self, ctx: RunContext, phase: Phase) -> None:
        # Out of budget before this phase. If we never produced a draft, stop as
        # budget_exhausted with partial results visible in admin (§6.4).
        repo.set_status(ctx.run.id, ResearchRunStatus.budget_exhausted.value)
        log.warning("research run budget-exhausted", extra={"fields": {
            "run": ctx.run.id, "phase": phase.value, "remaining": ctx.budget.remaining()}})
