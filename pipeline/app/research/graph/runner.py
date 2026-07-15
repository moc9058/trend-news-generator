"""Runs one leased research run through the graph (design §4.1, §6.1).

Replaces ResearchHarness. The graph owns phase transitions; this module owns
everything around them: deciding what to feed a resumed run, projecting supersteps
onto the run document the admin reads, honouring cancel, and cleaning up.
"""

from typing import Optional

from langgraph.types import Command

from app.config import get_settings
from app.repo import research as repo
from app.research.budget import Budget
from app.research.graph.builder import default_graph
from app.research.graph.context import ResearchRuntimeContext
from app.research.graph.state import merge_budget
from app.research.schemas import Phase, ResearchRun, ResearchRunStatus
from app.utils.logging import get_logger

log = get_logger(__name__)

# superstep -> the phase the admin should show. Only phase-carrying nodes are
# mapped: M2's dispatch/worker nodes and the plan_gate/budget_stop bookkeeping
# nodes project nothing, so the flow view never shows a phase the run is not in
# and the run doc is written once per phase (at its barrier), not once per worker.
NODE_PHASE: dict[str, str] = {
    "plan": Phase.plan.value,
    "gather_triage": Phase.gather.value,
    "extract_join": Phase.extract.value,
    "coverage": Phase.verify.value,
    "localize_join": Phase.write.value,
    "review": Phase.review.value,
}

# Worst case superstep count: each fanned phase is now 3 supersteps (dispatch,
# workers, barrier), so 2 gather loops + 1 revise ≈ 38 — over the default 25.
RECURSION_LIMIT = 50


def _initial_state(run: ResearchRun) -> dict:
    return {
        "run": run,
        "budget": run.budget.model_copy(deep=True),
        "hit_index": {}, "hit_rqs": {}, "selected": [],
        "claims": [], "coverage": None,
        "draft": None, "localized": {}, "audit": None,
        "review_decision": "", "revisions": 0, "post_id": "", "stop_reason": "",
    }


def _config(run: ResearchRun) -> dict:
    return {
        "configurable": {"thread_id": run.id},
        "recursion_limit": RECURSION_LIMIT,
        "max_concurrency": get_settings().research_max_concurrency,
        "run_name": f"research:{run.id}",
        "tags": ["research", "format:report", f"trigger:{run.trigger}"],
        # session_id/thread_id are what LangSmith groups a Threads view by, so the
        # pre- and post-approval executions of one run read as a single thread.
        "metadata": {"session_id": run.id, "thread_id": run.id,
                     "runId": run.id, "categoryId": run.categoryId},
    }


def run_research(run: ResearchRun, *, graph=None, context=None) -> dict:
    """Drive one claimed run to a stopping point (terminal, or a pause for approval).

    Returns the final channel values (`{}` when it stopped before running). The
    job ignores this; it exists because `audit` and `coverage` are the run's only
    artifacts NOT mirrored into Firestore, and the checkpoint holding them is torn
    down on success — so returning them here is the only way to assert on them.

    Exceptions propagate to generate_report.main, which marks the run failed; the
    last completed superstep is durable (durability="sync"), so the next claim
    resumes from there rather than from the top.
    """
    if _cancelled(run.id):
        # Checked before the graph runs, not just between supersteps: cancelling a
        # queued run must not pay for a plan first (the harness checked at the top
        # of its loop, and claim_next happily claims a cancelRequested run).
        repo.set_status(run.id, ResearchRunStatus.cancelled.value)
        log.info("research run cancelled", extra={"fields": {"run": run.id}})
        return {}

    graph = graph or default_graph()
    config = _config(run)
    snapshot = graph.get_state(config)

    graph_input = _decide_input(run, snapshot)
    if graph_input is _AWAIT_APPROVAL:
        repo.set_status(run.id, ResearchRunStatus.awaiting_plan_approval.value,
                        phase=Phase.gather.value)
        return {}

    budget_state = run.budget
    if snapshot.values:
        # Either side may be stale: the doc is written per superstep, the
        # checkpoint holds the last completed one. max-merge keeps spend honest.
        budget_state = merge_budget(run.budget, snapshot.values.get("budget"))
    budget = Budget(budget_state)

    if context is None:
        from app.research.fetch.fetcher import Fetcher
        from app.research.sources.base import build_registry
        # ONE Budget for both, as the harness did: deep_research's one-shot gate
        # reads drCallsUsed off this instance.
        context = ResearchRuntimeContext(
            budget=budget, registry=build_registry(budget),
            fetcher=Fetcher(), run_id=run.id)

    for chunk in graph.stream(graph_input, config, context=context,
                              stream_mode="updates", durability="sync"):
        if "__interrupt__" in chunk:
            repo.set_status(run.id, ResearchRunStatus.awaiting_plan_approval.value,
                            phase=Phase.gather.value)
            log.info("research run awaiting plan approval",
                     extra={"fields": {"run": run.id}})
            return graph.get_state(config).values
        for node, update in chunk.items():
            _project(run.id, node, update)
        repo.heartbeat(run.id)
        if _cancelled(run.id):
            # Leave the checkpoint: it costs nothing (TTL reaps it) and keeps the
            # partial run inspectable in admin.
            repo.set_status(run.id, ResearchRunStatus.cancelled.value)
            log.info("research run cancelled", extra={"fields": {"run": run.id}})
            return graph.get_state(config).values

    final = graph.get_state(config).values
    if final.get("stop_reason") == "budget_exhausted":
        repo.set_status(run.id, ResearchRunStatus.budget_exhausted.value)
        log.warning("research run budget-exhausted", extra={"fields": {"run": run.id}})
        return final

    # review's handoff already wrote postId + awaiting_review. Only tear the
    # checkpoint down once that is confirmed on the document — if anything else
    # happened, the thread is the only way to resume.
    cur = repo.get(run.id)
    if cur and cur.status == ResearchRunStatus.awaiting_review.value:
        _delete_thread(graph, run.id)
    return final


_AWAIT_APPROVAL = object()  # sentinel: pause without touching the graph


def _decide_input(run: ResearchRun, snapshot):
    """What to feed graph.stream(): fresh state, a resume, or a continuation."""
    if not snapshot.values:
        if run.phase != Phase.plan.value:
            # A run started under the old harness (or whose checkpoints have aged
            # out). Restarting is safe rather than merely tolerable: evidence and
            # claims are idempotent by id, handoff no-ops when postId is set, and
            # the already-spent budget rides along in the run document's cap.
            log.warning("resuming a run with no checkpoint — restarting from plan",
                        extra={"fields": {"run": run.id, "phase": run.phase}})
        return _initial_state(run)

    if any(task.interrupts for task in snapshot.tasks):
        if not run.planApproved:
            # Someone re-triggered the job without approving. Re-assert the pause
            # rather than resuming an unapproved plan.
            return _AWAIT_APPROVAL
        return Command(resume=True)

    if snapshot.next:
        return None  # crash resume: continue the unfinished superstep

    # Checkpointed, no pending work, yet not terminal — should not happen.
    log.warning("checkpoint has no next step; restarting from plan",
                extra={"fields": {"run": run.id}})
    return _initial_state(run)


def _project(run_id: str, node: str, update) -> None:
    """Mirror a superstep onto the run document the admin reads directly."""
    phase = NODE_PHASE.get(node)
    if phase is None:
        return
    fields: dict = {"phase": phase}
    if isinstance(update, dict) and update.get("budget") is not None:
        fields["budget"] = update["budget"].model_dump()
    repo.update_fields(run_id, fields)


def _cancelled(run_id: str) -> bool:
    cur = repo.get(run_id)
    return bool(cur and cur.cancelRequested)


def _delete_thread(graph, run_id: str) -> None:
    saver = getattr(graph, "checkpointer", None)
    if saver is None:
        return
    try:
        saver.delete_thread(run_id)
    except Exception as exc:  # noqa: BLE001 — cleanup must not fail a finished run
        log.warning("checkpoint cleanup failed (TTL will reap)",
                    extra={"fields": {"run": run_id, "error": str(exc)}})
