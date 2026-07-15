"""Graph topology (design §4.1).

M1 keeps the harness's shape exactly: a straight line plan→gather→extract→verify
→write→review with two loop-backs (verify→gather, review→write) and a budget
escape from every phase that has a floor. What changes is who drives it — the
113-line while loop is gone, and every superstep is checkpointed.

Routing convention: nodes that branch return `Command(goto=...)` and declare
`destinations=` for the diagram; nodes that do not branch use a static edge. The
two are never mixed on one node, which would route it twice.
"""

from functools import lru_cache

from langgraph.graph import END, START, StateGraph

from app.research.graph.context import ResearchRuntimeContext
from app.research.graph.nodes import extract, gather, plan, review, verify, write
from app.research.graph.nodes.common import budget_stop
from app.research.graph.state import ResearchState


def _assert_no_delta_channels(compiled) -> None:
    """checkpointer.py stores each checkpoint as ONE opaque blob, which is only
    correct while no channel is a DeltaChannel (whose partial updates must be
    applied against a base checkpoint). Plain binary reducers compile to
    BinaryOperatorAggregate; this fails loudly if that ever stops being true."""
    for name, channel in compiled.channels.items():
        if type(channel).__name__ == "DeltaChannel":
            raise AssertionError(
                f"channel {name!r} is a DeltaChannel; FirestoreCheckpointSaver's "
                "whole-blob storage cannot represent it (see checkpointer.py)")


def build_graph(checkpointer):
    """Compile the research graph. A checkpointer is REQUIRED — `interrupt()` (the
    plan-approval gate) cannot suspend without one, and tests must pass an
    InMemorySaver rather than compiling bare."""
    g = StateGraph(ResearchState, context_schema=ResearchRuntimeContext)

    g.add_node("plan", plan.plan_node, destinations=("plan_gate",))
    g.add_node("plan_gate", plan.plan_gate)
    g.add_node("gather", gather.gather_node, destinations=("extract", "budget_stop"))
    g.add_node("extract", extract.extract_node, destinations=("verify", "budget_stop"))
    g.add_node("verify", verify.verify_node,
               destinations=("gather", "write", "budget_stop"))
    g.add_node("write", write.write_node, destinations=("review", "budget_stop"))
    g.add_node("review", review.review_node, destinations=("write", END, "budget_stop"))
    g.add_node("budget_stop", budget_stop)

    g.add_edge(START, "plan")
    g.add_edge("plan_gate", "gather")
    g.add_edge("budget_stop", END)

    compiled = g.compile(checkpointer=checkpointer)
    _assert_no_delta_channels(compiled)
    return compiled


@lru_cache
def default_graph():
    """The production graph, compiled once per process."""
    from app.research.graph.checkpointer import FirestoreCheckpointSaver

    return build_graph(FirestoreCheckpointSaver())
