"""extract — fetch, snapshot and LLM-extract evidence (design §4.1)."""

from langgraph.runtime import Runtime
from langgraph.types import Command

from app.research import events
from app.research.graph.context import ResearchRuntimeContext
from app.research.graph.nodes.common import afford, budget_snapshot, make_ctx, state_delta
from app.research.graph.state import ResearchState
from app.research.phases import extract as extract_phase
from app.research.schemas import Phase


def extract_node(state: ResearchState, runtime: Runtime[ResearchRuntimeContext]) -> Command:
    # The fetch cap is enforced per-document inside the phase, as before; this only
    # gates entry on the USD floor.
    if not afford(state, runtime.context, Phase.extract):
        return Command(goto="budget_stop", update=budget_snapshot(runtime.context))
    ctx = make_ctx(state, runtime.context)
    run_id = ctx.run.id
    events.phase_start(run_id, Phase.extract.value)
    extract_phase.run(ctx)
    events.phase_end(run_id, Phase.extract.value)
    return Command(goto="verify", update=state_delta(ctx))
