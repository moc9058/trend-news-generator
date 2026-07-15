"""gather — retrieval + triage (design §4.1)."""

from langgraph.runtime import Runtime
from langgraph.types import Command

from app.research import events
from app.research.graph.context import ResearchRuntimeContext
from app.research.graph.nodes.common import afford, budget_snapshot, make_ctx, state_delta
from app.research.graph.state import ResearchState
from app.research.phases import gather as gather_phase
from app.research.schemas import Phase


def gather_node(state: ResearchState, runtime: Runtime[ResearchRuntimeContext]) -> Command:
    if not afford(state, runtime.context, Phase.gather):
        return Command(goto="budget_stop", update=budget_snapshot(runtime.context))
    ctx = make_ctx(state, runtime.context)
    run_id = ctx.run.id
    events.phase_start(run_id, Phase.gather.value)
    gather_phase.run(ctx)
    events.phase_end(run_id, Phase.gather.value)
    return Command(goto="extract", update=state_delta(ctx))
