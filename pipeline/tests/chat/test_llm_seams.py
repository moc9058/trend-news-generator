"""The two additive seams chat opens in shared code.

Both are compatibility contracts with the LangGraph migration (plan §9): chat may
extend `research/llm.py` and `generators/openai_client.py`, but must not shift
their default behaviour by a hair. These tests pin that.
"""

from types import SimpleNamespace

import pytest

import app.research.events as events_mod
import app.research.llm as llm_mod
from app.generators import openai_client
from app.models import TokenUsage
from app.research.budget import Budget
from app.research.schemas import BudgetState

from pydantic import BaseModel


class _Out(BaseModel):
    value: str


@pytest.fixture
def fake_json(monkeypatch):
    def _generate_json(model, system, user, usage):
        usage.inputTokens += 100
        usage.outputTokens += 20
        usage.costUsd = round(usage.costUsd + 0.01, 6)
        return {"value": "ok"}
    monkeypatch.setattr(llm_mod, "generate_json", _generate_json)


# --------------------------------------------------------------------------- #
# structured(event_sink=...)                                                   #
# --------------------------------------------------------------------------- #

def test_default_path_still_writes_a_research_audit_event(fake_json, monkeypatch):
    """No event_sink → unchanged: the event goes to researchRuns/{id}/events."""
    seen = []
    monkeypatch.setattr(events_mod, "llm_call",
                        lambda *a, **kw: seen.append((a, kw)))
    budget = Budget(BudgetState(usdCap=1.0))
    out = llm_mod.structured(_Out, "gpt-5.6-luna", "sys", "user",
                             budget=budget, run_id="rr_1", phase="plan", actor="planner")
    assert out.value == "ok"
    assert len(seen) == 1
    assert seen[0][0][0] == "rr_1"
    assert budget.state.usdSpent == 0.01


def test_event_sink_diverts_the_event_and_writes_no_ghost_doc(fake_json, monkeypatch):
    """A chat threadId must never reach researchRuns/{id}/events."""
    written = []
    monkeypatch.setattr(events_mod, "llm_call",
                        lambda *a, **kw: written.append(a))
    sink = []
    budget = Budget(BudgetState(usdCap=1.0))
    llm_mod.structured(_Out, "gpt-5.6-luna", "sys", "user", budget=budget,
                       run_id="ct_1", phase="research", actor="planner",
                       event_sink=sink.append)

    assert written == []                       # nothing hit Firestore
    assert len(sink) == 1
    assert sink[0]["actor"] == "planner"
    assert sink[0]["costUsd"] == 0.01
    assert budget.state.usdSpent == 0.01       # still charged


def test_event_sink_receives_validation_failures_too(monkeypatch):
    monkeypatch.setattr(llm_mod, "generate_json",
                        lambda m, s, u, usage: {"wrong": "shape"})
    monkeypatch.setattr(events_mod, "llm_call", lambda *a, **kw: pytest.fail("wrote to Firestore"))
    sink = []
    with pytest.raises(llm_mod.ResearchLLMError):
        llm_mod.structured(_Out, "gpt-5.6-luna", "sys", "user",
                           budget=Budget(BudgetState(usdCap=1.0)), run_id="ct_1",
                           phase="research", actor="planner", event_sink=sink.append)
    assert len(sink) == 1
    assert sink[0]["ok"] is False
    assert sink[0]["error"]


# --------------------------------------------------------------------------- #
# stream_text                                                                  #
# --------------------------------------------------------------------------- #

def _chunk(delta=None, usage=None):
    choices = ([SimpleNamespace(delta=SimpleNamespace(content=delta))]
               if delta is not None else [])
    return SimpleNamespace(choices=choices, usage=usage)


@pytest.fixture
def fake_openai(monkeypatch):
    sent = {}

    def _create(**kw):
        sent.update(kw)
        return iter([
            _chunk("Hello"), _chunk(" world"),
            # OpenAI sends usage last, in a chunk with no choices.
            _chunk(usage=SimpleNamespace(prompt_tokens=1000, completion_tokens=200)),
        ])

    monkeypatch.setattr(openai_client, "_client", lambda: SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=_create))))
    return sent


def test_stream_text_yields_deltas_and_accounts_usage_at_the_end(fake_openai):
    usage = TokenUsage()
    out = list(openai_client.stream_text(
        "gpt-5.6-luna", "sys", [{"role": "user", "content": "hi"}], usage))

    assert out == ["Hello", " world"]
    assert usage.inputTokens == 1000
    assert usage.outputTokens == 200
    # luna is (1.00, 6.00) per 1M: 1000*1 + 200*6 = 2200 / 1e6
    assert usage.costUsd == pytest.approx(0.0022)


def test_stream_text_prepends_system_and_requests_usage(fake_openai):
    usage = TokenUsage()
    list(openai_client.stream_text("gpt-5.6-luna", "SYS",
                                   [{"role": "user", "content": "hi"}], usage))
    assert fake_openai["messages"][0] == {"role": "system", "content": "SYS"}
    assert fake_openai["messages"][1] == {"role": "user", "content": "hi"}
    assert fake_openai["stream"] is True
    assert fake_openai["stream_options"] == {"include_usage": True}


def test_generate_json_is_unchanged_by_the_streaming_addition(monkeypatch):
    """The migration keeps generate_json as-is; prove we didn't disturb it."""
    def _create(**kw):
        assert "stream" not in kw
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content='{"a": 1}'))],
            usage=SimpleNamespace(prompt_tokens=10, completion_tokens=2))

    monkeypatch.setattr(openai_client, "_client", lambda: SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=_create))))
    usage = TokenUsage()
    assert openai_client.generate_json("gpt-5.6-luna", "s", "u", usage) == {"a": 1}
    assert usage.inputTokens == 10
