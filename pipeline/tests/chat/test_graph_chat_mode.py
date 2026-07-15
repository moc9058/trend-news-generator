"""Sparring mode: history goes to the model, tokens stream, no tools run."""

from app.chat.graph import build_graph
from app.chat.schemas import ChatMode


def _state(**kw):
    return {"thread_id": "ct_1", "assistant_message_id": "m1",
            "mode": ChatMode.chat.value, "user_input": "Is my premise sound?",
            "history": [], **kw}


def test_chat_mode_streams_tokens_and_skips_research(fake_stream, ctx_factory):
    graph = build_graph()
    ctx = ctx_factory()
    chunks = list(graph.stream(_state(), context=ctx, stream_mode="custom"))

    tokens = [c["data"]["delta"] for c in chunks if c["type"] == "token"]
    assert "".join(tokens).strip() == "answer from sparring"
    # No research progress events: sparring must not plan/search/read.
    assert not [c for c in chunks if c["type"] == "status"]
    assert len(fake_stream) == 1
    assert fake_stream[0]["actor"] == "sparring"
    assert fake_stream[0]["model"] == "gpt-5.6-sol"


def test_chat_mode_sends_prior_history_and_current_input(fake_stream, ctx_factory):
    history = [{"role": "user", "content": "first"},
               {"role": "assistant", "content": "reply"}]
    graph = build_graph()
    graph.invoke(_state(history=history), context=ctx_factory())

    sent = fake_stream[0]["messages"]
    assert [m["content"] for m in sent] == ["first", "reply", "Is my premise sound?"]
    assert "thinking partner" in fake_stream[0]["system"]


def test_chat_mode_answer_and_no_sources_land_in_state(fake_stream, ctx_factory):
    graph = build_graph()
    final = graph.invoke(_state(), context=ctx_factory())
    assert final["answer"] == "answer from sparring"
    assert final["sources"] == []
    assert final.get("stop_reason", "") == ""


def test_chat_mode_cancel_midstream_marks_cancelled(fake_stream, ctx_factory):
    graph = build_graph()
    ctx = ctx_factory(cancel_check=lambda: True)
    final = graph.invoke(_state(), context=ctx)
    assert final["stop_reason"] == "cancelled"
