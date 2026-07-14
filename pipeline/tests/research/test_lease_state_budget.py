"""P1: deterministic control — lease/resume predicate, phase transitions, budget."""

from datetime import datetime, timedelta, timezone

import app.repo.research as rr
from app.research.budget import Budget
from app.research.schemas import (
    AuditReport,
    BudgetState,
    CoverageReport,
    Phase,
    ResearchRun,
    RqCoverage,
)
from app.research.state import (
    critic_decision,
    gap_decision,
    is_stale,
    is_terminal,
    linear_next,
)

NOW = datetime(2026, 8, 1, 0, 0, tzinfo=timezone.utc)


# ---------- lease predicate (design §6.1) ----------

def test_claimable_queued_and_stale_running():
    assert rr._claimable("queued", None, NOW) is True
    # running with a fresh heartbeat → owned by a live worker, not claimable
    assert rr._claimable("running", NOW - timedelta(minutes=5), NOW) is False
    # running whose lease lapsed (crash) → resumable
    assert rr._claimable("running", NOW - timedelta(minutes=45), NOW) is True
    # running with no heartbeat at all → stale
    assert rr._claimable("running", None, NOW) is True


def test_claimable_rejects_terminal_and_unknown():
    for status in ("completed", "failed", "cancelled", "awaiting_review", "budget_exhausted"):
        assert rr._claimable(status, None, NOW) is False
    assert rr._claimable("awaiting_plan_approval", None, NOW) is False


def test_is_stale_thresholds():
    assert is_stale(None, NOW) is True
    assert is_stale(NOW - timedelta(minutes=29), NOW) is False
    assert is_stale(NOW - timedelta(minutes=31), NOW) is True


def test_is_terminal():
    assert all(is_terminal(s) for s in
               ("completed", "failed", "cancelled", "awaiting_review", "budget_exhausted"))
    assert not any(is_terminal(s) for s in ("queued", "running", "awaiting_plan_approval"))
    assert is_terminal("bogus") is False


# ---------- phase transitions (design §4.1) ----------

def test_linear_next_walks_the_order_and_stops_after_review():
    assert linear_next(Phase.plan) is Phase.gather
    assert linear_next(Phase.gather) is Phase.extract
    assert linear_next(Phase.extract) is Phase.verify
    assert linear_next(Phase.verify) is Phase.write
    assert linear_next(Phase.write) is Phase.review
    assert linear_next(Phase.review) is None


def _coverage(resolved_flags):
    return CoverageReport(rqCoverage=[
        RqCoverage(rqId=f"rq{i}", resolved=r) for i, r in enumerate(resolved_flags)])


def test_gap_decision_loops_only_when_allowed():
    unresolved = _coverage([True, False])
    resolved = _coverage([True, True])
    # unresolved, under loop cap, budget ok → loop
    assert gap_decision(unresolved, loops=0, max_loops=2, can_afford_gather=True) == "loop"
    # loop ceiling reached → finalize (surface gaps, don't loop forever)
    assert gap_decision(unresolved, loops=2, max_loops=2, can_afford_gather=True) == "finalize"
    # out of budget → finalize even if unresolved
    assert gap_decision(unresolved, loops=0, max_loops=2, can_afford_gather=False) == "finalize"
    # everything resolved → finalize
    assert gap_decision(resolved, loops=0, max_loops=2, can_afford_gather=True) == "finalize"


def test_critic_decision_revises_at_most_once():
    fail = AuditReport(passed=False)
    ok = AuditReport(passed=True)
    assert critic_decision(fail, revisions=0) == "revise"
    assert critic_decision(fail, revisions=1) == "proceed"   # max reached
    assert critic_decision(ok, revisions=0) == "proceed"


# ---------- budget (design §6.4) ----------

def test_budget_charges_and_reports_remaining():
    b = Budget(BudgetState(usdCap=10.0))
    spent = b.charge_llm("gpt-5.6-luna", 1_000_000, 0)  # $1.00/1M input
    assert spent == 1.0 and b.state.usdSpent == 1.0
    b.charge_usd(2.0)  # a Deep Research call
    assert b.remaining() == 7.0


def test_budget_prices_gpt56_tiers():
    b = Budget(BudgetState(usdCap=100.0))
    assert b.charge_llm("gpt-5.6-sol", 1_000_000, 1_000_000) == 35.0    # 5 + 30
    assert b.charge_llm("gpt-5.6-terra", 1_000_000, 1_000_000) == 17.5  # 2.5 + 15
    assert b.charge_llm("gpt-5.6-luna", 1_000_000, 1_000_000) == 7.0    # 1 + 6


def test_budget_can_afford_gates_phase_entry():
    b = Budget(BudgetState(usdCap=10.0, usdSpent=9.7))  # $0.30 left
    assert b.can_afford(Phase.review) is True   # floor 0.30
    assert b.can_afford(Phase.write) is False   # floor 1.00 → graceful degrade
    assert b.exhausted() is False
    b.charge_usd(0.3)
    assert b.exhausted() is True and b.can_afford(Phase.review) is False


def test_budget_fetch_and_deep_research_ceilings():
    b = Budget(BudgetState(usdCap=10.0, fetchCap=2))
    assert b.fetch_available() is True
    b.note_fetch(); b.note_fetch()
    assert b.fetch_available() is False
    assert b.deep_research_allowed() is True
    b.note_deep_research()
    assert b.deep_research_allowed() is False  # one-shot
    tight = Budget(BudgetState(usdCap=10.0, usdSpent=8.0))  # $2 < $3 min
    assert tight.deep_research_allowed() is False


# ---------- run id ----------

def test_new_run_id_format():
    rid = rr.new_run_id(now=datetime(2026, 8, 1, tzinfo=timezone.utc), rand="x7k2m9")
    assert rid == "rr_20260801_x7k2m9"


# ---------- claim_next selection (fake Firestore; txn stubbed) ----------

class _FakeRef:
    def __init__(self, doc_id, data):
        self.id = doc_id
        self._data = data


class _FakeSnap:
    def __init__(self, doc_id, data):
        self.id = doc_id
        self._data = data
        self.reference = _FakeRef(doc_id, data)

    def to_dict(self):
        return self._data


class _FakeQuery:
    def __init__(self, snaps):
        self._snaps = snaps

    def where(self, *a, **k):
        return self

    def order_by(self, *a, **k):
        return self  # test passes candidates pre-sorted by createdAt

    def limit(self, *a, **k):
        return self

    def get(self):
        return self._snaps


class _FakeClient:
    def __init__(self, snaps):
        self._snaps = snaps

    def collection(self, name):
        return _FakeQuery(self._snaps)


def _stub_txn(_client, ref, worker_id, now):
    data = {**ref._data, "status": "running", "claimedBy": worker_id,
            "claimedAt": now, "heartbeatAt": now}
    return ResearchRun(id=ref.id, **data)


def test_claim_next_picks_oldest_claimable_and_skips_fresh_running(monkeypatch):
    snaps = [
        _FakeSnap("run_fresh", {"status": "running", "createdAt": NOW,
                                "heartbeatAt": NOW - timedelta(minutes=1)}),   # live worker → skip
        _FakeSnap("run_queued", {"status": "queued", "createdAt": NOW}),        # claim this
        _FakeSnap("run_stale", {"status": "running", "createdAt": NOW,
                                "heartbeatAt": NOW - timedelta(minutes=50)}),   # would also be claimable
    ]
    monkeypatch.setattr(rr, "db", lambda: _FakeClient(snaps))
    monkeypatch.setattr(rr, "_run_claim_txn", _stub_txn)

    claimed = rr.claim_next("worker-abc", now=NOW)
    assert claimed is not None
    assert claimed.id == "run_queued"      # fresh running skipped, oldest claimable taken
    assert claimed.status == "running" and claimed.claimedBy == "worker-abc"


def test_claim_next_returns_none_when_nothing_claimable(monkeypatch):
    snaps = [_FakeSnap("run_fresh", {"status": "running", "createdAt": NOW,
                                     "heartbeatAt": NOW - timedelta(minutes=1)})]
    monkeypatch.setattr(rr, "db", lambda: _FakeClient(snaps))
    monkeypatch.setattr(rr, "_run_claim_txn", _stub_txn)
    assert rr.claim_next("worker-abc", now=NOW) is None
