"""P3/P4: golden plan→review integration test (design §8.1 L2).

Runs the full research graph end-to-end with the LLM, connectors, fetcher, GCS and
Firestore mocked. Asserts the DoD: a 3-language draft Post(format=report) is
produced, citecheck passes, contested coverage has ≥2 stances, and the science
golden's arXiv:1706.03762 flows into evidence with the right tier.

Ported from test_harness_golden.py in M1 with the assertions UNCHANGED — that is
the point of the file. Only the seam moved (ResearchHarness.run -> the graph via
runner.run_research); if the port had altered behaviour, these would fail. It
gains what the harness could not be tested for: crash resume, the interrupt-based
approval gate, and cancel between supersteps.
"""

import pytest
from langgraph.checkpoint.memory import InMemorySaver

import app.research.llm as llm
from app.models import AppSettings
from app.repo import configs
from app.research.schemas import BudgetState, ResearchRun
from tests.research.conftest import (
    FakeConn,
    academic_hit,
    drive,
    kokkai_hit,
    news_hit,
)

pytestmark = pytest.mark.usefixtures("fake_llm")


def _run(run_id="rr_20260801_test01", **kw) -> ResearchRun:
    defaults = dict(
        trigger="manual", requestedBy="u@example.com",
        categoryId="geopolitics-history", theme="天皇の戦争への責任",
        budget=BudgetState(usdCap=10.0), languages=["ja", "ko", "en"],
        canonicalLanguage="ja", status="running", phase="plan")
    defaults.update(kw)
    return ResearchRun(id=run_id, **defaults)


# --------------------------------------------------------------------------- #

def test_golden_full_run_produces_trilingual_report_post(store):
    run = _run()
    store.runs[run.id] = run

    final, _ = drive(run)

    # reached handoff → awaiting_review, Post created
    assert store.runs[run.id].status == "awaiting_review"
    assert store.runs[run.id].postId and final["post_id"] == store.runs[run.id].postId
    post = store.posts[final["post_id"]]
    assert post.format.value == "report" and post.researchRunId == run.id

    # three languages present in the draft Post
    assert set(post.localizations.keys()) == {"ja", "ko", "en"}
    assert post.localizations["ja"].title == "調査報告書"

    # evidence: kokkai (primary) + academic arXiv + news, with arXiv:1706.03762 present
    ev = store.evidence[run.id]
    assert len(ev) == 3
    arxiv = [e for e in ev.values() if e.identifiers.get("arxivId") == "1706.03762"]
    assert arxiv and arxiv[0].tier == "primary"
    kokkai = [e for e in ev.values() if e.sourceType == "parliamentary_record"]
    assert kokkai and kokkai[0].tier == "primary"

    # contested coverage: ≥2 stances represented across claims
    stances = {c.stance for c in final["claims"] if c.stance}
    assert {"positionA", "positionB"} <= stances

    # citecheck 100% (all cited evidenceIds exist) + 3 languages consistent + passed
    audit = final["audit"]
    assert audit is not None
    assert audit.citeCheckPassRate == 1.0
    assert audit.triLanguageConsistent is True
    assert audit.passed is True

    # coverage finalized (both RQs have ≥2 evidence) — no unresolved loop needed
    assert final["coverage"] is not None and final["coverage"].decision == "finalize"


def test_golden_run_restarts_legacy_run_without_checkpoint(store):
    # A pre-consolidation run stored with phase="R0" is bridged by the compat shim
    # (LEGACY_PHASE_MAP); with no checkpoint to resume, the runner restarts it from
    # plan and it completes end-to-end.
    run = _run("rr_legacy", phase="R0")
    assert run.phase == "plan"  # shim applied at model build
    store.runs[run.id] = run

    drive(run)

    assert store.runs[run.id].status == "awaiting_review"
    assert store.runs[run.id].postId


def test_verify_loops_back_to_gather_until_loop_ceiling(store):
    # rq2's connectors never return hits → rq2 stays unresolved → the verify
    # coverage leg loops back to gather until research_max_loops (2), then
    # finalizes with the gap surfaced (§6.4 — never silently dropped).
    class _Rq1OnlyConn(FakeConn):
        def search(self, q):
            return super().search(q) if q.rqId == "rq1" else []

    registry = {"kokkai": _Rq1OnlyConn("kokkai", [kokkai_hit()]),
                "academic": _Rq1OnlyConn("academic", [academic_hit()]),
                "news": _Rq1OnlyConn("news", [news_hit()])}
    run = _run("rr_loop", languages=["ja"])
    store.runs[run.id] = run

    final, _ = drive(run, registry)

    assert store.runs[run.id].loops == 2  # looped twice, then hit the ceiling
    assert final["coverage"] is not None and final["coverage"].decision == "finalize"
    unresolved = [rq for rq in final["coverage"].rqCoverage if not rq.resolved]
    assert [rq.rqId for rq in unresolved] == ["rq2"]
    assert store.runs[run.id].status == "awaiting_review"  # still handed off


def test_review_revise_loops_back_to_write_once(store, monkeypatch):
    # First critic verdict fails → review loops back to write for one corrective
    # rewrite; second verdict passes → handoff runs.
    orig = llm.structured
    calls = {"critic": 0, "writer": 0}

    def wrapper(schema, model, system, user, **kw):
        actor = kw.get("actor")
        if actor == "writer":
            calls["writer"] += 1
        if actor == "critic":
            calls["critic"] += 1
            if calls["critic"] == 1:
                return schema.model_validate({"findings": [
                    {"kind": "unsupported_assertion", "location": "s1",
                     "detail": "no citation", "action": "delete"}], "passed": False})
        return orig(schema, model, system, user, **kw)
    monkeypatch.setattr(llm, "structured", wrapper)

    run = _run("rr_revise")
    store.runs[run.id] = run

    final, _ = drive(run)

    assert calls == {"critic": 2, "writer": 2}  # one corrective rewrite
    assert final["revisions"] == 1
    assert store.runs[run.id].status == "awaiting_review"
    assert store.runs[run.id].postId


def test_review_revise_disabled_by_setting_forces_proceed(store, monkeypatch):
    # researchReviseEnabled=False caps max_revisions at 0: even a failed first
    # critic verdict must proceed straight to handoff, no corrective rewrite.
    monkeypatch.setattr(configs, "app_settings",
                        lambda: AppSettings(researchReviseEnabled=False))
    orig = llm.structured
    calls = {"critic": 0, "writer": 0}

    def wrapper(schema, model, system, user, **kw):
        actor = kw.get("actor")
        if actor == "writer":
            calls["writer"] += 1
        if actor == "critic":
            calls["critic"] += 1
            if calls["critic"] == 1:
                return schema.model_validate({"findings": [
                    {"kind": "unsupported_assertion", "location": "s1",
                     "detail": "no citation", "action": "delete"}], "passed": False})
        return orig(schema, model, system, user, **kw)
    monkeypatch.setattr(llm, "structured", wrapper)

    run = _run("rr_revise_off")
    store.runs[run.id] = run

    final, _ = drive(run)

    assert calls == {"critic": 1, "writer": 1}  # no corrective rewrite
    assert final["revisions"] == 0
    assert store.runs[run.id].status == "awaiting_review"
    assert store.runs[run.id].postId


def test_gather_falls_back_to_raw_rq_when_refinement_fails(store, monkeypatch):
    # Query-refinement LLM failure must degrade to the raw RQ text and still
    # search the connectors — never fail the gather phase.
    orig = llm.structured

    def wrapper(schema, model, system, user, **kw):
        if kw.get("actor") == "retriever":
            raise llm.ResearchLLMError("refinement broke")
        return orig(schema, model, system, user, **kw)
    monkeypatch.setattr(llm, "structured", wrapper)

    queries_seen = []

    class _RecordingConn(FakeConn):
        def search(self, q):
            queries_seen.append(q.query)
            return super().search(q)

    registry = {"kokkai": _RecordingConn("kokkai", [kokkai_hit()]),
                "academic": _RecordingConn("academic", [academic_hit()]),
                "news": _RecordingConn("news", [news_hit()])}
    run = _run("rr_fallback", languages=["ja"])
    store.runs[run.id] = run

    drive(run, registry)

    # raw RQ texts were used as queries (fixture RQs from the planner fake)
    assert "戦前の天皇の法的権限" in queries_seen
    assert store.runs[run.id].status == "awaiting_review"
    assert store.evidence[run.id]  # evidence still produced


def test_golden_citecheck_flags_hallucinated_citation(store):
    # A writer that cites a non-existent evidenceId must fail citecheck.
    from app.research.fetch import citecheck
    from app.research.schemas import EvidenceRecord, ReportDraft
    ev = [EvidenceRecord(evidenceId="real1"), EvidenceRecord(evidenceId="real2")]
    good = ReportDraft(references=["real1", "real2"])
    bad = ReportDraft(references=["real1", "ghost99"])
    assert citecheck.verify_quotes(good, ev).passed is True
    audit = citecheck.verify_quotes(bad, ev)
    assert audit.passed is False and audit.citeCheckPassRate == 0.5
    assert audit.findings[0].kind == "hallucinated_citation"


# --------------------------------------------------------------------------- #
# M2: fan-out specifics                                                        #
# --------------------------------------------------------------------------- #

def test_fanout_single_phase_event_pair(store, monkeypatch):
    """However many workers a phase fans out, the admin sees ONE start/end pair.

    Three RQs × three connectors = nine gather workers; the flow view must still
    count exactly one gather traversal. Also pins that the workers genuinely ran
    on multiple threads — without that, M2 is just M1 with extra supersteps.
    """
    import threading

    orig = llm.structured

    def wide_planner(schema, model, system, user, **kw):
        if kw.get("actor") == "planner":
            return schema.model_validate({
                "themeClass": "politics_history", "contested": False,
                "rqs": [{"id": f"rq{i}", "q": f"問い{i}",
                         "strategies": ["kokkai", "academic", "news"]}
                        for i in (1, 2, 3)]})
        return orig(schema, model, system, user, **kw)
    monkeypatch.setattr(llm, "structured", wide_planner)

    threads_seen = set()

    class _ThreadTrackingConn(FakeConn):
        def search(self, q):
            threads_seen.add(threading.get_ident())
            return super().search(q)

    registry = {"kokkai": _ThreadTrackingConn("kokkai", [kokkai_hit()]),
                "academic": _ThreadTrackingConn("academic", [academic_hit()]),
                "news": _ThreadTrackingConn("news", [news_hit()])}
    run = _run("rr_fanout", languages=["ja"])
    store.runs[run.id] = run

    drive(run, registry)

    evs = [ev for rid, ev in store.events if rid == run.id]
    searches = [ev for ev in evs if ev.action == "connector_search"]
    assert len(searches) >= 9, "3 RQs × 3 connectors should all have searched"
    for phase in ("gather", "extract", "verify", "write"):
        starts = sum(1 for ev in evs if ev.phase == phase and ev.action == "phase_start")
        ends = sum(1 for ev in evs if ev.phase == phase and ev.action == "phase_end")
        assert (starts, ends) == (1, 1), f"{phase}: {starts} starts / {ends} ends"
    assert len(threads_seen) > 1, "workers must actually run on parallel threads"
    assert store.runs[run.id].status == "awaiting_review"


def test_claims_buffer_reset_on_second_verify_pass(store):
    """A verify->gather loop must not carry the previous pass's claims forward.

    The sequential code overwrote ctx.claims wholesale each pass; the accumulator
    channel would instead append across passes — the dispatch's RESET is what
    restores the old semantics. Without it, this run's three verify passes would
    stack 3× the claims into write's input.
    """
    class _Rq1OnlyConn(FakeConn):
        def search(self, q):
            return super().search(q) if q.rqId == "rq1" else []

    registry = {"kokkai": _Rq1OnlyConn("kokkai", [kokkai_hit()]),
                "academic": _Rq1OnlyConn("academic", [academic_hit()]),
                "news": _Rq1OnlyConn("news", [news_hit()])}
    run = _run("rr_buf", languages=["ja"])
    store.runs[run.id] = run

    final, _ = drive(run, registry)

    assert store.runs[run.id].loops == 2  # three verify passes ran in total
    # one pass's worth of claims (the verifier fake emits 2 per RQ with evidence),
    # not three passes' worth stacked up
    assert len(final["claims"]) == 2
    assert len({c.claimId for c in final["claims"]}) == len(final["claims"])
    assert len(final["claims_buf"]) == 2  # the buffer holds only the last pass


# --------------------------------------------------------------------------- #
# What the harness could not do                                               #
# --------------------------------------------------------------------------- #

def test_plan_approval_interrupt_pause_and_resume(store, monkeypatch):
    """The gate pauses at a checkpoint and resumes without re-planning.

    Under the harness the whole run restarted after approval and re-paid for the
    plan; here the checkpoint holds it, so the planner is called exactly once
    across both executions.
    """
    planner_calls = {"n": 0}
    orig = llm.structured

    def counting(schema, model, system, user, **kw):
        if kw.get("actor") == "planner":
            planner_calls["n"] += 1
        return orig(schema, model, system, user, **kw)
    monkeypatch.setattr(llm, "structured", counting)

    saver = InMemorySaver()
    run = _run("rr_gate", planApproval=True, languages=["ja"])
    store.runs[run.id] = run

    drive(run, saver=saver)

    assert store.runs[run.id].status == "awaiting_plan_approval"
    assert store.runs[run.id].phase == "gather"
    assert planner_calls["n"] == 1
    assert not store.runs[run.id].postId  # nothing written yet

    # admin approves → approve-plan writes planApproved + re-queues the run
    store.runs[run.id].planApproved = True
    store.runs[run.id].status = "queued"
    drive(store.runs[run.id], saver=saver)

    assert store.runs[run.id].status == "awaiting_review"
    assert store.runs[run.id].postId
    assert planner_calls["n"] == 1, "the plan must be reused, not re-purchased"


def test_awaiting_approval_run_retriggered_without_approval_stays_paused(store):
    """Re-running the job must not sneak an unapproved plan past the gate."""
    saver = InMemorySaver()
    run = _run("rr_gate2", planApproval=True, languages=["ja"])
    store.runs[run.id] = run
    drive(run, saver=saver)
    assert store.runs[run.id].status == "awaiting_plan_approval"

    # job re-triggered (e.g. a stale-lease takeover) with planApproved still False
    store.runs[run.id].status = "running"
    drive(store.runs[run.id], saver=saver)

    assert store.runs[run.id].status == "awaiting_plan_approval"
    assert not store.runs[run.id].postId


def test_crash_after_write_resumes_review_with_draft(store, monkeypatch):
    """Regression for the empty-Post bug the harness had (plan §0.4).

    The harness kept draft/localized in memory only and persisted "the last phase
    that completed". A crash in review therefore resumed with an empty context:
    citecheck saw zero references, returned a vacuous 1.0, the audit passed, and a
    Post with an empty body was created. Here review's inputs are checkpointed, so
    the retried superstep sees the real draft.
    """
    orig = llm.structured
    boom = {"fire": True}

    def wrapper(schema, model, system, user, **kw):
        if kw.get("actor") == "critic" and boom["fire"]:
            boom["fire"] = False
            raise RuntimeError("simulated crash inside review")
        return orig(schema, model, system, user, **kw)
    monkeypatch.setattr(llm, "structured", wrapper)

    saver = InMemorySaver()
    run = _run("rr_crash")
    store.runs[run.id] = run

    with pytest.raises(RuntimeError):
        drive(run, saver=saver)
    assert not store.posts, "nothing should have been handed off yet"

    # the job retries (same lease, same thread) and continues from the checkpoint
    boom["fire"] = False
    final, _ = drive(store.runs[run.id], saver=saver)

    assert len(store.posts) == 1, "exactly one Post, not one per attempt"
    post = store.posts[final["post_id"]]
    assert post.localizations["ja"].body, "the draft survived the crash"
    assert final["audit"].citeCheckPassRate == 1.0
    # the vacuous-pass signature of the old bug: a 1.0 rate over zero references
    assert final["draft"] is not None and final["draft"].references


def test_event_sequence_matches_admin_contract(store):
    """The admin flow view is DERIVED from these events; admin code did not change.

    Its rules (docs 07 / plan contract D): exactly one phase_start/phase_end pair
    per phase traversal, the revise edge counted as "write phase_starts - 1", the
    loop edge from run.loops, and connector_search events nested under gather.
    Breaking any of these silently draws the wrong diagram, which no assertion in
    the admin would catch.
    """
    run = _run("rr_events", languages=["ja"])
    store.runs[run.id] = run

    drive(run)

    evs = [ev for rid, ev in store.events if rid == run.id]
    pairs = [(ev.phase, ev.action) for ev in evs
             if ev.action in ("phase_start", "phase_end")]

    # one start and one end per traversal, and they alternate — never a start
    # without its end, which would leave a phase spinning in the UI.
    for phase in ("plan", "gather", "extract", "verify", "write", "review"):
        starts = pairs.count((phase, "phase_start"))
        ends = pairs.count((phase, "phase_end"))
        assert starts == ends, f"{phase}: {starts} starts vs {ends} ends"
        assert starts >= 1, f"{phase} never ran"
    assert [a for _, a in pairs] == ["phase_start", "phase_end"] * (len(pairs) // 2)

    # this golden neither loops nor revises: exactly one pass each
    assert pairs.count(("write", "phase_start")) == 1
    assert store.runs[run.id].loops == 0

    # connector_search events belong to gather, and carry the hit count the
    # fan-out display reads
    searches = [ev for ev in evs if ev.action == "connector_search"]
    assert searches, "the flow view draws its connector fan-out from these"
    assert all(ev.phase == "gather" for ev in searches)
    assert all("hits" in ev.detail for ev in searches)

    # actors stay inside the vocabulary the admin knows
    known = {"harness", "planner", "selector", "retriever", "triage", "extractor",
             "verifier", "writer", "localizer", "critic",
             "kokkai", "academic", "news", "gov_docs", "books", "ieee",
             "web_grounded", "deep_research", "fetcher"}
    assert {ev.actor for ev in evs} <= known


def test_revise_adds_exactly_one_write_phase_start(store, monkeypatch):
    """The admin derives the revise edge from the write phase_start count."""
    orig = llm.structured
    critics = {"n": 0}

    def wrapper(schema, model, system, user, **kw):
        if kw.get("actor") == "critic":
            critics["n"] += 1
            if critics["n"] == 1:
                return schema.model_validate({"findings": [
                    {"kind": "unsupported_assertion", "location": "s",
                     "detail": "d", "action": "delete"}], "passed": False})
        return orig(schema, model, system, user, **kw)
    monkeypatch.setattr(llm, "structured", wrapper)

    run = _run("rr_ev_revise", languages=["ja"])
    store.runs[run.id] = run

    final, _ = drive(run)

    evs = [ev for rid, ev in store.events if rid == run.id]
    write_starts = sum(1 for ev in evs
                       if ev.phase == "write" and ev.action == "phase_start")
    assert write_starts == 2
    assert write_starts - 1 == final["revisions"] == 1


def test_golden_run_through_the_firestore_checkpointer(store):
    """The real saver, driving the real graph, on real research state.

    test_checkpointer_firestore.py exercises the saver against synthetic values;
    this is the one that would catch a channel the serializer chokes on, or state
    that outgrows a Firestore document (kokkai hits carry full speech text).
    """
    from tests.research.test_checkpointer_firestore import FakeFirestore

    from app.research.graph.checkpointer import FirestoreCheckpointSaver

    fs = FakeFirestore()
    saver = FirestoreCheckpointSaver(client=fs, ttl_days=14)
    run = _run("rr_fs", languages=["ja"])
    store.runs[run.id] = run

    final, _ = drive(run, saver=saver)

    assert store.runs[run.id].status == "awaiting_review"
    assert final["draft"] is not None
    # the run succeeded, so the thread is torn down rather than left to the TTL
    assert [p for p in fs.data if p.startswith("researchRuns/rr_fs/")] == []


def test_crash_resume_through_the_firestore_checkpointer(store, monkeypatch):
    """Checkpoints really do survive a crash when written to (fake) Firestore."""
    from tests.research.test_checkpointer_firestore import FakeFirestore

    from app.research.graph.checkpointer import FirestoreCheckpointSaver

    orig = llm.structured
    boom = {"fire": True}

    def wrapper(schema, model, system, user, **kw):
        if kw.get("actor") == "critic" and boom["fire"]:
            boom["fire"] = False
            raise RuntimeError("crash in review")
        return orig(schema, model, system, user, **kw)
    monkeypatch.setattr(llm, "structured", wrapper)

    fs = FakeFirestore()
    saver = FirestoreCheckpointSaver(client=fs, ttl_days=14)
    run = _run("rr_fs_crash", languages=["ja"])
    store.runs[run.id] = run

    with pytest.raises(RuntimeError):
        drive(run, saver=saver)
    assert [p for p in fs.data if p.startswith("researchRuns/rr_fs_crash/checkpoints/")], \
        "the crash must leave a checkpoint behind to resume from"

    final, _ = drive(store.runs[run.id], saver=FirestoreCheckpointSaver(client=fs,
                                                                       ttl_days=14))
    assert store.runs[run.id].status == "awaiting_review"
    assert len(store.posts) == 1
    assert final["draft"] is not None


def test_cancel_between_supersteps(store):
    """A cancel flagged mid-run stops it at the next superstep boundary."""
    run = _run("rr_cancel", languages=["ja"])
    store.runs[run.id] = run

    # flag the cancel as soon as the first phase has run
    real_update = store.runs[run.id]

    class _CancelAfterPlan:
        def __init__(self):
            self.armed = False

    marker = _CancelAfterPlan()
    orig_get = None

    import app.repo.research as rr_repo
    orig_get = rr_repo.get

    def get_with_cancel(rid):
        cur = orig_get(rid)
        if cur is not None and marker.armed:
            cur.cancelRequested = True
        marker.armed = True  # arm after the first poll (which is the pre-run check)
        return cur
    rr_repo.get = get_with_cancel
    try:
        drive(run)
    finally:
        rr_repo.get = orig_get

    assert store.runs[run.id].status == "cancelled"
    assert not store.runs[run.id].postId
    assert real_update.status == "cancelled"
