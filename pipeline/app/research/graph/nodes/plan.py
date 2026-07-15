"""plan + the plan-approval gate (design §4.1)."""

from langgraph.runtime import Runtime
from langgraph.types import Command, interrupt

from app.research import events
from app.research.graph.context import ResearchRuntimeContext
from app.research.graph.nodes.common import make_ctx, state_delta
from app.research.graph.state import ResearchState
from app.research.phases import plan as plan_phase
from app.research.schemas import Phase
from app.utils.logging import get_logger

log = get_logger(__name__)


def plan_node(state: ResearchState, runtime: Runtime[ResearchRuntimeContext]) -> Command:
    """Theme -> ResearchPlan. No budget gate: plan has no floor (budget.PHASE_MIN_USD)."""
    ctx = make_ctx(state, runtime.context)
    run_id = ctx.run.id
    events.phase_start(run_id, Phase.plan.value)
    plan_phase.run(ctx)
    events.phase_end(run_id, Phase.plan.value)
    return Command(goto="plan_gate", update=state_delta(ctx))


def plan_gate(state: ResearchState, runtime: Runtime[ResearchRuntimeContext]) -> dict:
    """Optional human sign-off on the plan before any money is spent gathering.

    `interrupt()` suspends the graph here; the checkpoint holds everything, and the
    admin approve-plan endpoint re-queues the run. On resume LangGraph re-runs this
    node from the top and `interrupt()` RETURNS instead of raising, so the run
    continues into gather.

    Emits no events: this is a gate, not a phase, and the admin flow counts one
    phase_start/phase_end pair per phase (compatibility contract D).
    """
    run = state["run"]
    if not (run.planApproval and not run.planApproved):
        return {}
    interrupt({"reason": "plan_approval", "runId": run.id})
    # Reached only on resume. The checkpointed run still says planApproved=False
    # (approve-plan wrote it to Firestore, not into our state), so record it here.
    log.info("plan approved, resuming", extra={"fields": {"run": run.id}})
    return {"run": run.model_copy(update={"planApproved": True})}
