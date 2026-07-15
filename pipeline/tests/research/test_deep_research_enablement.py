"""Deep Research: registration, cost accounting and its single injection point (M0-c).

The connector existed but was never registered, so none of this was reachable in
production. Enabling it puts a ~$2-per-call tool inside a $10 run, which makes two
things load-bearing: it must be billed accurately, and it must be reachable from
exactly one place.
"""

import httpx
import pytest

from app.generators.openai_client import WEB_SEARCH_CALL_USD
from app.research.budget import DEEP_RESEARCH_MIN_USD, Budget
from app.research.phases.plan import STRATEGY_MATRIX, _inject_deep_research
from app.research.schemas import BudgetState, ResearchPlan, StrategyQuery
from app.research.sources.base import build_registry
from app.research.sources.deep_research import (
    DEEP_RESEARCH_FALLBACK_USD,
    DeepResearchConnector,
)


def _budget(cap=10.0, spent=0.0, dr_used=0):
    return Budget(BudgetState(usdCap=cap, usdSpent=spent, drCallsUsed=dr_used))


def _completed(input_tokens=1000, output_tokens=500, web_searches=0):
    """A completed Responses payload, shaped as the live API returns it.

    Field names verified against api.openai.com on 2026-07-15 (background mode):
    usage.{input_tokens,output_tokens,total_tokens} and
    tool_usage.web_search.num_requests. `billing` exists but carries only
    {"payer": ...} — no cost figure — which is why we price the call ourselves.
    """
    return {
        "status": "completed",
        "usage": {"input_tokens": input_tokens, "output_tokens": output_tokens,
                  "total_tokens": input_tokens + output_tokens},
        "tool_usage": {"web_search": {"num_requests": web_searches}},
        "billing": {"payer": "developer"},
        "output": [],
    }


# ---- registration ----------------------------------------------------------

def test_build_registry_includes_deep_research_with_budget():
    budget = _budget()
    registry = build_registry(budget)

    assert "deep_research" in registry
    # The connector must share the caller's Budget instance, or the one-shot gate
    # and the charges land on a different counter than the run's.
    assert registry["deep_research"]._budget is budget


def test_build_registry_omits_deep_research_without_budget():
    """Research chat builds a registry with no Budget; a $2 tool must not appear.

    Chat's whole per-message budget is $0.7 (quick) / $3.0 (deep). It also filters
    connectors through VALID_CONNECTORS, but that only excludes deep_research while
    it stays out of STRATEGY_MATRIX — so the registry keeps the guarantee itself.
    """
    registry = build_registry()

    assert "deep_research" not in registry
    assert {"kokkai", "academic", "gov_docs", "books", "ieee", "news",
            "web_grounded"} <= set(registry)


def test_deep_research_stays_out_of_the_strategy_matrix():
    """It is injected by code, never chosen by the planner (§4.3).

    In the matrix it would also reach research chat via VALID_CONNECTORS, and it
    would have to be added to PLAN_SYSTEM's connector enum.
    """
    for theme_class, row in STRATEGY_MATRIX.items():
        assert "deep_research" not in row, theme_class


# ---- cost accounting -------------------------------------------------------

def test_search_charges_tokens_and_web_searches(monkeypatch):
    budget = _budget()
    conn = DeepResearchConnector(client=httpx.Client(), budget=budget)
    monkeypatch.setattr(conn, "_start_and_poll",
                        lambda q: _completed(input_tokens=100_000,
                                             output_tokens=20_000, web_searches=90))

    conn.search(StrategyQuery(rqId="rq1", query="theme", language="ja"))

    # o4-mini-deep-research = $2.00/$8.00 per 1M -> 0.20 + 0.16 = $0.36 of tokens,
    # plus 90 web searches at $0.01 = $0.90. The tool half dominates, which is the
    # whole reason token-only pricing was not enough.
    assert budget.state.drCallsUsed == 1
    assert budget.state.usdSpent == pytest.approx(0.36 + 0.90)
    assert 90 * WEB_SEARCH_CALL_USD == pytest.approx(0.90)


def test_search_charges_fallback_when_usage_missing(monkeypatch):
    """A poll timeout returns {} — we were still billed, so estimate rather than 0."""
    budget = _budget()
    conn = DeepResearchConnector(client=httpx.Client(), budget=budget)
    monkeypatch.setattr(conn, "_start_and_poll", lambda q: {})

    conn.search(StrategyQuery(rqId="rq1", query="theme", language="ja"))

    assert budget.state.usdSpent == pytest.approx(DEEP_RESEARCH_FALLBACK_USD)
    assert budget.state.drCallsUsed == 1


def test_search_tolerates_a_payload_without_tool_usage(monkeypatch):
    """Charge tokens and move on if the tool_usage block is absent."""
    budget = _budget()
    conn = DeepResearchConnector(client=httpx.Client(), budget=budget)
    payload = _completed(input_tokens=1_000_000, output_tokens=0)
    payload.pop("tool_usage")
    monkeypatch.setattr(conn, "_start_and_poll", lambda q: payload)

    conn.search(StrategyQuery(rqId="rq1", query="theme", language="ja"))

    assert budget.state.usdSpent == pytest.approx(2.00)  # 1M input @ $2.00/1M


def test_failed_call_is_free_and_non_fatal(monkeypatch):
    budget = _budget()
    conn = DeepResearchConnector(client=httpx.Client(), budget=budget)

    def _boom(q):
        raise httpx.ConnectError("upstream down")
    monkeypatch.setattr(conn, "_start_and_poll", _boom)

    assert conn.search(StrategyQuery(rqId="rq1", query="t", language="ja")) == []
    assert budget.state.usdSpent == 0.0
    assert budget.state.drCallsUsed == 0  # a call that never started is not the one shot


# ---- the gates -------------------------------------------------------------

def test_one_shot_gate_blocks_a_second_call(monkeypatch):
    budget = _budget(dr_used=1)
    conn = DeepResearchConnector(client=httpx.Client(), budget=budget)
    monkeypatch.setattr(conn, "_start_and_poll",
                        lambda q: pytest.fail("must not call the API a second time"))

    assert conn.search(StrategyQuery(rqId="rq1", query="t", language="ja")) == []
    assert budget.state.usdSpent == 0.0


def test_low_balance_gate_skips_without_charging(monkeypatch):
    """Below the floor DR must not fire — it could not be paid for."""
    budget = _budget(cap=10.0, spent=10.0 - (DEEP_RESEARCH_MIN_USD - 0.01))
    conn = DeepResearchConnector(client=httpx.Client(), budget=budget)
    monkeypatch.setattr(conn, "_start_and_poll",
                        lambda q: pytest.fail("must not call the API when broke"))

    assert conn.search(StrategyQuery(rqId="rq1", query="t", language="ja")) == []
    assert budget.state.drCallsUsed == 0


def test_provider_off_skips(monkeypatch):
    from app.config import get_settings

    monkeypatch.setenv("DEEP_RESEARCH_PROVIDER", "off")
    get_settings.cache_clear()
    try:
        budget = _budget()
        conn = DeepResearchConnector(client=httpx.Client(), budget=budget)
        monkeypatch.setattr(conn, "_start_and_poll",
                            lambda q: pytest.fail("must not call the API when off"))
        assert conn.search(StrategyQuery(rqId="rq1", query="t", language="ja")) == []
        assert budget.state.usdSpent == 0.0
    finally:
        get_settings.cache_clear()


# ---- the single injection point --------------------------------------------

def test_plan_appends_deep_research_to_first_rq_only():
    plan = ResearchPlan(themeClass="politics_history", contested=False, rqs=[
        {"id": "rq1", "q": "q1", "strategies": ["kokkai", "gov_docs"]},
        {"id": "rq2", "q": "q2", "strategies": ["academic"]},
        {"id": "rq3", "q": "q3", "strategies": ["news"]}])

    _inject_deep_research(plan)

    # last on the central question: an assist, not a lead source
    assert plan.rqs[0].strategies == ["kokkai", "gov_docs", "deep_research"]
    assert plan.rqs[1].strategies == ["academic"]
    assert plan.rqs[2].strategies == ["news"]


def test_inject_deep_research_is_idempotent():
    """plan may be re-run on resume; the leg must not accumulate."""
    plan = ResearchPlan(themeClass="economics", contested=False,
                        rqs=[{"id": "rq1", "q": "q", "strategies": ["academic"]}])

    _inject_deep_research(plan)
    _inject_deep_research(plan)

    assert plan.rqs[0].strategies.count("deep_research") == 1


def test_inject_deep_research_handles_an_empty_plan():
    plan = ResearchPlan(themeClass="economics", contested=False, rqs=[])
    _inject_deep_research(plan)  # must not raise
    assert plan.rqs == []
