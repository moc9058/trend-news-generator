"""review — critic audit, then handoff on "proceed" (design §4.1)."""

from langgraph.graph import END
from langgraph.runtime import Runtime
from langgraph.types import Command

from app.research import events
from app.research.graph.context import ResearchRuntimeContext
from app.research.graph.nodes.common import afford, budget_snapshot, make_ctx, state_delta
from app.research.graph.state import ResearchState
from app.research.phases import review as review_phase
from app.research.schemas import Phase


def review_node(state: ResearchState, runtime: Runtime[ResearchRuntimeContext]) -> Command:
    if not afford(state, runtime.context, Phase.review):
        return Command(goto="budget_stop", update=budget_snapshot(runtime.context))
    ctx = make_ctx(state, runtime.context)
    run_id = ctx.run.id
    events.phase_start(run_id, Phase.review.value)
    # The phase stores the critic's decision and, on "proceed", runs the handoff
    # (creating the Post and moving the run to awaiting_review) — unchanged.
    review_phase.run(ctx)
    events.phase_end(run_id, Phase.review.value)

    # THE ONLY PLACE `revisions` IS INCREMENTED. Under the harness this counter
    # lived in memory, so a crash reset it and could grant an extra rewrite; it is
    # a channel now and survives in the checkpoint.
    if ctx.review_decision == "revise":
        return Command(goto="write",
                       update=state_delta(ctx, revisions=state.get("revisions", 0) + 1))
    return Command(goto=END, update=state_delta(ctx))
