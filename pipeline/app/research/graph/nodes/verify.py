"""verify — claim verification + the deterministic coverage/loop decision (§4.1)."""

from langgraph.runtime import Runtime
from langgraph.types import Command

from app.repo import research as repo
from app.research import events
from app.research.graph.context import ResearchRuntimeContext
from app.research.graph.nodes.common import afford, budget_snapshot, make_ctx, state_delta
from app.research.graph.state import ResearchState
from app.research.phases import verify as verify_phase
from app.research.schemas import Phase


def verify_node(state: ResearchState, runtime: Runtime[ResearchRuntimeContext]) -> Command:
    if not afford(state, runtime.context, Phase.verify):
        return Command(goto="budget_stop", update=budget_snapshot(runtime.context))
    ctx = make_ctx(state, runtime.context)
    run_id = ctx.run.id
    events.phase_start(run_id, Phase.verify.value)
    verify_phase.run(ctx)
    events.phase_end(run_id, Phase.verify.value)

    # The branch itself was already decided by the pure state.gap_decision inside
    # the phase (loop ceiling + budget + unresolved RQs); this only routes on it.
    # THE ONLY PLACE `loops` IS INCREMENTED.
    if ctx.coverage and ctx.coverage.decision == "loop":
        ctx.run.loops += 1
        repo.update_fields(run_id, {"loops": ctx.run.loops})
        return Command(goto="gather", update=state_delta(ctx))
    return Command(goto="write", update=state_delta(ctx))
