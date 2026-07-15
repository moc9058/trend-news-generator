"""runner.run_research control logic (design §6.1).

The graph decides phase transitions; this module decides what a resumed run is fed,
what the admin sees, and when the checkpoint may be destroyed. Those decisions are
unit-tested here against a stub graph — test_graph_golden.py covers them against
the real one.
"""

from types import SimpleNamespace

import pytest

import app.repo.research as rr_repo
from app.research.graph import runner
from app.research.graph.state import merge_budget
from app.research.schemas import BudgetState, ResearchRun


class _StubGraph:
    """A graph that records how it was driven and replays scripted chunks."""

    def __init__(self, snapshot=None, chunks=(), final=None):
        self._snapshot = snapshot or SimpleNamespace(values={}, tasks=(), next=())
        self._chunks = list(chunks)
        self._final = final if final is not None else {}
        self.streamed_with = []
        self.checkpointer = SimpleNamespace(deleted=[])
        self.checkpointer.delete_thread = self.checkpointer.deleted.append
        self._get_state_calls = 0

    def get_state(self, config):
        self._get_state_calls += 1
        # After the stream, get_state reports the final values.
        if self._get_state_calls == 1:
            return self._snapshot
        return SimpleNamespace(values=self._final, tasks=(), next=())

    def stream(self, graph_input, config, **kw):
        self.streamed_with.append((graph_input, config, kw))
        return iter(self._chunks)


@pytest.fixture
def store(monkeypatch):
    runs: dict = {}
    fields: list = []

    monkeypatch.setattr(rr_repo, "get", lambda rid: runs.get(rid))
    monkeypatch.setattr(rr_repo, "heartbeat", lambda rid, now=None: None)

    def _update_fields(rid, f):
        fields.append((rid, f))
        run = runs.get(rid)
        for k, v in f.items():
            if run is not None and k != "budget":
                setattr(run, k, v)
    monkeypatch.setattr(rr_repo, "update_fields", _update_fields)

    def _set_status(rid, status, **extra):
        _update_fields(rid, {"status": status, **extra})
    monkeypatch.setattr(rr_repo, "set_status", _set_status)
    return SimpleNamespace(runs=runs, fields=fields)


def _run(**kw) -> ResearchRun:
    defaults = dict(id="rr_1", theme="t", budget=BudgetState(usdCap=10.0),
                    status="running", phase="plan")
    defaults.update(kw)
    return ResearchRun(**defaults)


def _ctx():
    from app.research.budget import Budget
    from app.research.graph.context import ResearchRuntimeContext
    return ResearchRuntimeContext(budget=Budget(BudgetState(usdCap=10.0)),
                                  registry={}, fetcher=None, run_id="rr_1")


# ---- input decision matrix -------------------------------------------------

def test_fresh_run_gets_initial_state(store):
    run = _run()
    store.runs[run.id] = run
    graph = _StubGraph()

    runner.run_research(run, graph=graph, context=_ctx())

    graph_input = graph.streamed_with[0][0]
    assert isinstance(graph_input, dict)
    assert graph_input["run"] is run
    assert graph_input["revisions"] == 0 and graph_input["stop_reason"] == ""


def test_crash_resume_passes_none_to_continue(store):
    """A checkpoint with unfinished work resumes; it must not restart from plan."""
    run = _run(phase="extract")
    store.runs[run.id] = run
    snapshot = SimpleNamespace(values={"run": run, "budget": run.budget},
                               tasks=(), next=("verify",))
    graph = _StubGraph(snapshot=snapshot)

    runner.run_research(run, graph=graph, context=_ctx())

    assert graph.streamed_with[0][0] is None


def test_pending_interrupt_with_approval_resumes(store):
    from langgraph.types import Command

    run = _run(planApproval=True, planApproved=True)
    store.runs[run.id] = run
    snapshot = SimpleNamespace(
        values={"run": run}, next=("plan_gate",),
        tasks=(SimpleNamespace(interrupts=("i",)),))
    graph = _StubGraph(snapshot=snapshot)

    runner.run_research(run, graph=graph, context=_ctx())

    assert isinstance(graph.streamed_with[0][0], Command)
    assert graph.streamed_with[0][0].resume is True


def test_pending_interrupt_without_approval_repauses_without_streaming(store):
    """Guards a hand re-triggered job from resuming an unapproved plan."""
    run = _run(planApproval=True, planApproved=False)
    store.runs[run.id] = run
    snapshot = SimpleNamespace(
        values={"run": run}, next=("plan_gate",),
        tasks=(SimpleNamespace(interrupts=("i",)),))
    graph = _StubGraph(snapshot=snapshot)

    runner.run_research(run, graph=graph, context=_ctx())

    assert graph.streamed_with == []
    assert run.status == "awaiting_plan_approval"
    assert run.phase == "gather"


def test_legacy_run_without_checkpoint_restarts_from_plan(store):
    run = _run(phase="verify")  # mid-run under the old harness, no checkpoint
    store.runs[run.id] = run
    graph = _StubGraph()

    runner.run_research(run, graph=graph, context=_ctx())

    assert isinstance(graph.streamed_with[0][0], dict)  # restart, not resume


def test_checkpoint_with_no_next_step_restarts(store):
    """Defensive: a checkpoint that is neither interrupted nor advancing."""
    run = _run()
    store.runs[run.id] = run
    snapshot = SimpleNamespace(values={"run": run}, tasks=(), next=())
    graph = _StubGraph(snapshot=snapshot)

    runner.run_research(run, graph=graph, context=_ctx())

    assert isinstance(graph.streamed_with[0][0], dict)


# ---- budget reconciliation -------------------------------------------------

def test_budget_merges_run_doc_and_checkpoint_by_max():
    doc = BudgetState(usdCap=10.0, usdSpent=3.0, fetchUsed=5, drCallsUsed=0)
    ckpt = BudgetState(usdCap=10.0, usdSpent=7.5, fetchUsed=2, drCallsUsed=1)

    merged = merge_budget(doc, ckpt)

    # spend never goes backwards: taking either side alone could lose a charge
    # and let the run overspend its cap.
    assert merged.usdSpent == 7.5
    assert merged.fetchUsed == 5
    assert merged.drCallsUsed == 1
    assert merged.usdCap == 10.0


def test_merge_budget_tolerates_a_missing_side():
    b = BudgetState(usdCap=10.0, usdSpent=1.0)
    assert merge_budget(b, None) is b
    assert merge_budget(None, b) is b


# ---- superstep projection --------------------------------------------------

def test_phase_nodes_project_onto_the_run_document(store):
    run = _run()
    store.runs[run.id] = run
    budget = BudgetState(usdCap=10.0, usdSpent=2.0)
    graph = _StubGraph(chunks=[{"gather": {"budget": budget}}])

    runner.run_research(run, graph=graph, context=_ctx())

    projected = [f for rid, f in store.fields if "phase" in f]
    assert projected[0]["phase"] == "gather"
    assert projected[0]["budget"]["usdSpent"] == 2.0


def test_bookkeeping_nodes_project_nothing(store):
    """plan_gate/budget_stop are not phases; the flow view must not show them."""
    run = _run()
    store.runs[run.id] = run
    graph = _StubGraph(chunks=[{"plan_gate": {}}, {"budget_stop": {"stop_reason": "x"}}])

    runner.run_research(run, graph=graph, context=_ctx())

    assert [f for rid, f in store.fields if "phase" in f] == []


def test_projection_without_a_budget_update_still_sets_phase(store):
    run = _run()
    store.runs[run.id] = run
    graph = _StubGraph(chunks=[{"review": {"post_id": "p1"}}])

    runner.run_research(run, graph=graph, context=_ctx())

    assert [f for rid, f in store.fields if "phase" in f] == [{"phase": "review"}]


# ---- terminal handling -----------------------------------------------------

def test_interrupt_chunk_pauses_the_run(store):
    run = _run(planApproval=True)
    store.runs[run.id] = run
    graph = _StubGraph(chunks=[{"plan": {}}, {"__interrupt__": ("i",)}])

    runner.run_research(run, graph=graph, context=_ctx())

    assert run.status == "awaiting_plan_approval"
    assert run.phase == "gather"
    assert graph.checkpointer.deleted == []  # the pause NEEDS its checkpoint


def test_budget_exhausted_is_reported_and_keeps_its_checkpoint(store):
    run = _run()
    store.runs[run.id] = run
    graph = _StubGraph(chunks=[{"budget_stop": {"stop_reason": "budget_exhausted"}}],
                       final={"stop_reason": "budget_exhausted"})

    runner.run_research(run, graph=graph, context=_ctx())

    assert run.status == "budget_exhausted"
    assert graph.checkpointer.deleted == []  # TTL reaps it; no need to race


def test_cancel_before_the_graph_runs_costs_nothing(store):
    """Cancelling a queued run must not pay for a plan first."""
    run = _run(cancelRequested=True)
    store.runs[run.id] = run
    graph = _StubGraph()

    runner.run_research(run, graph=graph, context=_ctx())

    assert graph.streamed_with == []
    assert run.status == "cancelled"


def test_cancel_between_supersteps_stops_the_stream(store, monkeypatch):
    run = _run()
    store.runs[run.id] = run
    polls = {"n": 0}

    def _get(rid):
        cur = store.runs.get(rid)
        polls["n"] += 1
        if polls["n"] > 1:  # not the pre-run check: flag it mid-stream
            cur.cancelRequested = True
        return cur
    monkeypatch.setattr(rr_repo, "get", _get)

    graph = _StubGraph(chunks=[{"plan": {}}, {"gather": {}}])
    runner.run_research(run, graph=graph, context=_ctx())

    assert run.status == "cancelled"


def test_thread_is_deleted_only_after_awaiting_review(store):
    run = _run()
    store.runs[run.id] = run
    graph = _StubGraph(chunks=[{"review": {"post_id": "p1"}}], final={"post_id": "p1"})
    run.status = "awaiting_review"  # review's handoff wrote this

    runner.run_research(run, graph=graph, context=_ctx())

    assert graph.checkpointer.deleted == ["rr_1"]


def test_thread_is_kept_when_the_run_did_not_reach_awaiting_review(store):
    """If anything unexpected happened, the checkpoint is the only way back."""
    run = _run(status="running")
    store.runs[run.id] = run
    graph = _StubGraph(chunks=[{"review": {}}], final={})

    runner.run_research(run, graph=graph, context=_ctx())

    assert graph.checkpointer.deleted == []


def test_cleanup_failure_never_fails_a_finished_run(store):
    run = _run(status="awaiting_review")
    store.runs[run.id] = run
    graph = _StubGraph(chunks=[{"review": {}}], final={})

    def _boom(_):
        raise RuntimeError("firestore down")
    graph.checkpointer.delete_thread = _boom

    runner.run_research(run, graph=graph, context=_ctx())  # must not raise


# ---- stream configuration --------------------------------------------------

def test_stream_is_configured_for_durability_and_langsmith(store):
    run = _run(id="rr_1", trigger="scheduled", categoryId="tech")
    store.runs[run.id] = run
    graph = _StubGraph()

    runner.run_research(run, graph=graph, context=_ctx())

    _, config, kw = graph.streamed_with[0]
    # sync durability is what makes the last completed superstep survive a crash
    assert kw["durability"] == "sync"
    assert kw["stream_mode"] == "updates"
    assert config["configurable"]["thread_id"] == "rr_1"
    assert config["recursion_limit"] == runner.RECURSION_LIMIT
    # LangSmith groups a Threads view by these, so both executions of an
    # approval-gated run read as one thread.
    assert config["metadata"]["session_id"] == "rr_1"
    assert config["metadata"]["thread_id"] == "rr_1"
    assert "trigger:scheduled" in config["tags"]
