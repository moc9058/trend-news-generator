"""Graph topology (design §4.1, M2 fan-out).

Six phases, same order, same two loop-backs as ever — but gather / extract /
verify / write are each now a dispatch → parallel workers → barrier triple.
Workers run on threads under `config={"max_concurrency": N}`; triage and
coverage stay barriers on purpose (they are quality gates that must see ALL of
the previous stage's output), and phase events keep their strict one-pair-per-
traversal contract by living only in the dispatch (start) and barrier (end).

Routing convention: nodes that branch return `Command(goto=...)` and declare
`destinations=` for the diagram; nodes that do not branch use a static edge. The
two are never mixed on one node, which would route it twice. Workers are plain
dict-returning nodes with a static edge to their barrier.
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

    g.add_node("gather_dispatch", gather.gather_dispatch,
               destinations=("gather_search", "gather_triage", "budget_stop"))
    g.add_node("gather_search", gather.gather_search)
    g.add_node("gather_triage", gather.gather_triage,
               destinations=("extract_dispatch",))

    g.add_node("extract_dispatch", extract.extract_dispatch,
               destinations=("extract_one", "extract_join", "budget_stop"))
    g.add_node("extract_one", extract.extract_one)
    g.add_node("extract_join", extract.extract_join)

    g.add_node("verify_dispatch", verify.verify_dispatch,
               destinations=("verify_rq", "coverage", "budget_stop"))
    g.add_node("verify_rq", verify.verify_rq)
    g.add_node("coverage", verify.coverage,
               destinations=("gather_dispatch", "write_canonical"))

    g.add_node("write_canonical", write.write_canonical,
               destinations=("localize_lang", "localize_join", "budget_stop"))
    g.add_node("localize_lang", write.localize_lang)
    g.add_node("localize_join", write.localize_join)

    g.add_node("review", review.review_node,
               destinations=("write_canonical", END, "budget_stop"))
    g.add_node("budget_stop", budget_stop)

    g.add_edge(START, "plan")
    g.add_edge("plan_gate", "gather_dispatch")
    g.add_edge("gather_search", "gather_triage")   # workers -> their barrier
    g.add_edge("extract_one", "extract_join")
    g.add_edge("extract_join", "verify_dispatch")
    g.add_edge("verify_rq", "coverage")
    g.add_edge("localize_lang", "localize_join")
    g.add_edge("localize_join", "review")
    g.add_edge("budget_stop", END)

    compiled = g.compile(checkpointer=checkpointer)
    _assert_no_delta_channels(compiled)
    return compiled


@lru_cache
def default_graph():
    """The production graph, compiled once per process."""
    from app.research.graph.checkpointer import FirestoreCheckpointSaver

    return build_graph(FirestoreCheckpointSaver())
