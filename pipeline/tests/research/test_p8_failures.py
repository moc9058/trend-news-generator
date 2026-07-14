"""P8: failure-pattern reproduction (design §7.3).

Covers the catalog patterns not already exercised elsewhere:
  * LLM JSON崩れ → pydantic validation → one corrective retry → skip/raise
  * 予算枯渇 → harness stops as budget_exhausted (graceful)
(hallucinated-citation, dead-link→Wayback, SSRF, robots, circuit-breaker,
academic fallback chain are covered in the connector / fetcher / golden tests.)
"""

import pytest

import app.repo.research as rr_repo
import app.research.llm as llm_mod
from app.research.budget import Budget
from app.research.context import RunContext
from app.research.harness import ResearchHarness
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
                     budget=_budget(), run_id="r", phase="R1", actor="planner")
    assert out.themeClass == "science_tech" and len(calls) == 1


def test_llm_structured_retries_once_then_succeeds(monkeypatch):
    seq = [INVALID, VALID]
    calls = []

    def fake(m, s, u, usage):
        calls.append(u)
        return seq.pop(0)
    monkeypatch.setattr(llm_mod, "generate_json", fake)
    out = structured(ResearchPlan, "m", "sys", "user",
                     budget=_budget(), run_id="r", phase="R1", actor="planner")
    assert out.themeClass == "science_tech"
    assert len(calls) == 2 and "failed validation" in calls[1]  # corrective retry


def test_llm_structured_raises_after_two_failures(monkeypatch):
    monkeypatch.setattr(llm_mod, "generate_json", lambda m, s, u, usage: INVALID)
    with pytest.raises(ResearchLLMError):
        structured(ResearchPlan, "m", "sys", "user",
                   budget=_budget(), run_id="r", phase="R1", actor="planner")


def test_harness_stops_as_budget_exhausted(monkeypatch):
    # remaining budget 0 → cannot afford R2 (floor $0.30) → graceful stop.
    run = ResearchRun(id="rrb", status="running", phase="R2",
                      budget=BudgetState(usdCap=1.0, usdSpent=1.0))
    store = {"rrb": run}
    monkeypatch.setattr(rr_repo, "get", lambda rid: store.get(rid))
    monkeypatch.setattr(rr_repo, "set_status",
                        lambda rid, s, **k: setattr(store[rid], "status", s))
    monkeypatch.setattr(rr_repo, "append_event", lambda rid, ev: None)

    harness = ResearchHarness(ctx_factory=lambda r: RunContext(run=r, budget=Budget(r.budget)))
    harness.run("rrb")
    assert store["rrb"].status == "budget_exhausted"
