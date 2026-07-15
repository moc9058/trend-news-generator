"""Shared node plumbing: the state <-> RunContext adapter and the budget guard.

M1 keeps the phase implementations untouched and has each node delegate to them,
so the port is provably behaviour-preserving (the golden test's assertions do not
move). `make_ctx`/`state_delta` are the seam between LangGraph's channel dicts and
the RunContext the phases still expect. M2 dissolves this by moving the phase
bodies into the nodes.
"""

from typing import Optional

from app.research import events
from app.research.context import RunContext
from app.research.graph.context import ResearchRuntimeContext
from app.research.graph.state import ResearchState
from app.research.schemas import Phase


def make_ctx(state: ResearchState, runtime_ctx: ResearchRuntimeContext) -> RunContext:
    """Build the RunContext a phase expects from the graph's channels.

    Note `hit_rqs` flips list -> set here: the phases work with sets, the channel
    stores sorted lists so it can be serialised into a checkpoint.
    """
    return RunContext(
        run=state["run"],
        budget=runtime_ctx.budget,
        registry=runtime_ctx.registry,
        fetcher=runtime_ctx.fetcher,
        hit_index=dict(state.get("hit_index") or {}),
        hit_rqs={k: set(v) for k, v in (state.get("hit_rqs") or {}).items()},
        selected=list(state.get("selected") or []),
        claims=list(state.get("claims") or []),
        coverage=state.get("coverage"),
        draft=state.get("draft"),
        localized=dict(state.get("localized") or {}),
        audit=state.get("audit"),
        review_decision=state.get("review_decision") or "",
        revisions=state.get("revisions") or 0,
        postId=state.get("post_id") or "",
    )


def state_delta(ctx: RunContext, **extra) -> dict:
    """Project a RunContext back onto channels after a phase has mutated it.

    Always snapshots the budget: `model_copy` because the live Budget keeps being
    charged after this node returns, and a checkpoint must record the value as of
    this superstep rather than alias a mutating object.
    """
    delta = {
        "run": ctx.run,
        "budget": ctx.budget.state.model_copy(deep=True),
        "hit_index": ctx.hit_index,
        "hit_rqs": {k: sorted(v) for k, v in ctx.hit_rqs.items()},
        "selected": ctx.selected,
        "claims": ctx.claims,
        "coverage": ctx.coverage,
        "draft": ctx.draft,
        "localized": ctx.localized,
        "audit": ctx.audit,
        "review_decision": ctx.review_decision,
        "post_id": ctx.postId,
    }
    delta.update(extra)
    return delta


def afford(state: ResearchState, runtime_ctx: ResearchRuntimeContext,
           phase: Phase) -> bool:
    """Budget gate, emitting the same `budget_check ok=false` the harness did.

    Deliberately checked BEFORE any phase_start, so a phase skipped for lack of
    budget produces no phase events at all and stays `pending` in the admin flow —
    matching the old harness exactly (compatibility contract D).
    """
    if runtime_ctx.budget.can_afford(phase):
        return True
    events.budget_check(state["run"].id, phase.value,
                        runtime_ctx.budget.remaining(), ok=False)
    return False


def budget_snapshot(runtime_ctx: ResearchRuntimeContext) -> dict:
    """The budget-only delta a stopping node returns."""
    return {"budget": runtime_ctx.budget.state.model_copy(deep=True)}


def budget_stop(state: ResearchState, runtime) -> dict:
    """Terminal marker for "ran out of budget before entering a phase".

    Only records why we stopped; runner.py turns this into the run's
    `budget_exhausted` status. The `budget_check ok=false` event was already
    emitted by afford(), at the phase that could not be entered.
    """
    return {"stop_reason": "budget_exhausted"}
