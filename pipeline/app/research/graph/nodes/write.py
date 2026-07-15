"""write — canonical draft + localizations (design §4.1)."""

from langgraph.runtime import Runtime
from langgraph.types import Command

from app.research import events
from app.research.graph.context import ResearchRuntimeContext
from app.research.graph.nodes.common import afford, budget_snapshot, make_ctx, state_delta
from app.research.graph.state import ResearchState
from app.research.phases import write as write_phase
from app.research.schemas import Phase


def write_node(state: ResearchState, runtime: Runtime[ResearchRuntimeContext]) -> Command:
    if not afford(state, runtime.context, Phase.write):
        return Command(goto="budget_stop", update=budget_snapshot(runtime.context))
    ctx = make_ctx(state, runtime.context)
    run_id = ctx.run.id
    # Also the re-entry point for a revise loop, so the admin flow derives its
    # revise edge from "number of write phase_starts - 1" (contract D).
    events.phase_start(run_id, Phase.write.value)
    write_phase.run(ctx)
    events.phase_end(run_id, Phase.write.value)
    return Command(goto="review", update=state_delta(ctx))
