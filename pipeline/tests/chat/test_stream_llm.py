"""stream_chat: the budget/audit discipline around a streamed completion."""

import app.chat.stream_llm as stream_mod
from app.chat.stream_llm import stream_chat
from app.research.budget import Budget
from app.research.schemas import BudgetState


def _fake_stream_text(deltas, cost=0.03, tokens=(80, 40)):
    def _stream(model, system, messages, usage):
        for d in deltas:
            yield d
        usage.inputTokens += tokens[0]
        usage.outputTokens += tokens[1]
        usage.costUsd = round(usage.costUsd + cost, 6)
    return _stream


def test_stream_chat_returns_text_charges_budget_and_audits(monkeypatch):
    monkeypatch.setattr(stream_mod, "stream_text", _fake_stream_text(["a", "b", "c"]))
    budget = Budget(BudgetState(usdCap=1.0))
    seen, events = [], []

    text, usage = stream_chat(
        model="gpt-5.6-sol", system="sys", messages=[{"role": "user", "content": "q"}],
        budget=budget, on_delta=seen.append, actor="sparring", phase="chat",
        events=events)

    assert text == "abc"
    assert seen == ["a", "b", "c"]
    assert budget.state.usdSpent == 0.03
    assert usage.inputTokens == 80
    assert events[0]["actor"] == "sparring"
    assert events[0]["action"] == "llm_stream"
    assert events[0]["promptVersion"].startswith("chat@")


def test_should_stop_halts_output_but_still_charges_full_usage(monkeypatch):
    monkeypatch.setattr(stream_mod, "stream_text", _fake_stream_text(list("abcdef")))
    budget = Budget(BudgetState(usdCap=1.0))
    seen = []

    text, _usage = stream_chat(
        model="gpt-5.6-sol", system="sys", messages=[], budget=budget,
        on_delta=seen.append, actor="sparring", phase="chat",
        should_stop=lambda: len(seen) >= 2)

    # The user stops seeing tokens at the cancel point...
    assert text == "ab"
    assert seen == ["a", "b"]
    # ...but OpenAI generated (and billed) the whole completion, so the stream is
    # drained to the usage chunk and the budget reflects the real cost.
    assert budget.state.usdSpent == 0.03


def test_events_are_optional(monkeypatch):
    monkeypatch.setattr(stream_mod, "stream_text", _fake_stream_text(["x"]))
    text, _ = stream_chat(model="m", system="s", messages=[],
                          budget=Budget(BudgetState(usdCap=1.0)),
                          on_delta=lambda d: None, actor="a", phase="p")
    assert text == "x"
