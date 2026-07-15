"""P8: failure-pattern reproduction (design §7.3).

Covers the catalog patterns not already exercised elsewhere:
  * LLM JSON崩れ → pydantic validation → one corrective retry → skip/raise
  * 予算枯渇 → the graph stops as budget_exhausted (graceful)
(hallucinated-citation, dead-link→Wayback, SSRF, robots, circuit-breaker,
academic fallback chain are covered in the connector / fetcher / golden tests.)
"""

import pytest

import app.repo.research as rr_repo
import app.research.llm as llm_mod
from app.research.budget import Budget
from app.research.llm import ResearchLLMError, structured
from app.research.schemas import BudgetState, ResearchPlan, ResearchRun

VALID = {"themeClass": "science_tech", "contested": False, "rqs": []}
INVALID = {"nope": "missing required themeClass"}


def _budget():
    return Budget(BudgetState(usdCap=10.0))


@pytest.fixture(autouse=True)
def _silence_events(monkeypatch):
    monkeypatch.setattr(llm_mod.events, "llm_call", lambda *a, **k: None)


def test_llm_structured_valid_first_try(monkeypatch):
    calls = []
    monkeypatch.setattr(llm_mod, "generate_json",
                        lambda m, s, u, usage: (calls.append(u), VALID)[1])
    out = structured(ResearchPlan, "m", "sys", "user",
                     budget=_budget(), run_id="r", phase="plan", actor="planner")
    assert out.themeClass == "science_tech" and len(calls) == 1


def test_llm_structured_retries_once_then_succeeds(monkeypatch):
    seq = [INVALID, VALID]
    calls = []

    def fake(m, s, u, usage):
        calls.append(u)
        return seq.pop(0)
    monkeypatch.setattr(llm_mod, "generate_json", fake)
    out = structured(ResearchPlan, "m", "sys", "user",
                     budget=_budget(), run_id="r", phase="plan", actor="planner")
    assert out.themeClass == "science_tech"
    assert len(calls) == 2 and "failed validation" in calls[1]  # corrective retry


def test_llm_structured_raises_after_two_failures(monkeypatch):
    monkeypatch.setattr(llm_mod, "generate_json", lambda m, s, u, usage: INVALID)
    with pytest.raises(ResearchLLMError):
        structured(ResearchPlan, "m", "sys", "user",
                   budget=_budget(), run_id="r", phase="plan", actor="planner")


def test_graph_stops_as_budget_exhausted(store, monkeypatch):
    """Remaining budget 0 → cannot afford gather (floor $0.70) → graceful stop.

    The plan phase has no floor, so it still runs; gather's guard then routes to
    budget_stop BEFORE emitting any phase event, leaving gather `pending` in the
    admin flow exactly as the harness did.
    """
    from tests.research.conftest import drive, install_fake_llm

    install_fake_llm(monkeypatch, store)
    run = ResearchRun(id="rrb", status="running", phase="plan", theme="t",
                      languages=["ja"], canonicalLanguage="ja",
                      budget=BudgetState(usdCap=1.0, usdSpent=1.0))
    store.runs[run.id] = run

    final, _ = drive(run)

    assert store.runs["rrb"].status == "budget_exhausted"
    assert final["stop_reason"] == "budget_exhausted"
    assert not store.runs["rrb"].postId  # no draft was fabricated
    # the skipped phase recorded its refusal, and no phase_start for it
    actions = [(ev.phase, ev.action) for _, ev in store.events]
    assert ("gather", "budget_check") in actions
    assert ("gather", "phase_start") not in actions
