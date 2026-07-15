"""deep research: LLM select, the gap loop, and its ceiling."""

from app.chat.graph import build_graph
from app.chat.schemas import ChatDepth, ChatMode

from .conftest import FakeConn, news_hit


def _state(**kw):
    return {"thread_id": "ct_1", "assistant_message_id": "m1",
            "mode": ChatMode.research.value, "depth": ChatDepth.deep.value,
            "user_input": "Trace this policy's history.", "history": [], **kw}


def test_deep_gap_check_finalizing_ends_the_run(fake_stream, fake_structured, ctx_factory):
    graph = build_graph()
    final = graph.invoke(_state(), context=ctx_factory(usd_cap=5.0))
    assert fake_structured["calls"] == ["planner", "gap"]
    assert final["loops"] == 0
    assert final["answer"] == "answer from synthesizer"


def test_deep_uses_llm_select_when_hits_exceed_the_cap(fake_stream, fake_structured, ctx_factory):
    many = [news_hit().model_copy(update={"url": f"https://www.reuters.com/a/{i}"})
            for i in range(20)]
    ctx = ctx_factory(usd_cap=5.0, fetch_cap=40,
                      registry={"kokkai": FakeConn("kokkai", many),
                                "academic": FakeConn("academic", [])})
    graph = build_graph()
    graph.invoke(_state(), context=ctx)
    assert "selector" in fake_structured["calls"]


def test_deep_gap_loop_runs_once_then_finalizes(fake_stream, fake_structured, ctx_factory):
    fake_structured["gap_decision"] = "loop"
    graph = build_graph()
    final = graph.invoke(_state(), context=ctx_factory(usd_cap=5.0))

    # One loop only: gap says "loop", we re-plan and re-read, then MAX_LOOPS
    # sends us to synthesize without asking the gap critic again.
    assert final["loops"] == 1
    assert fake_structured["calls"].count("gap") == 1
    assert final["answer"] == "answer from synthesizer"


def test_gap_loop_accumulates_hits_rather_than_replacing(fake_stream, fake_structured, ctx_factory):
    fake_structured["gap_decision"] = "loop"
    # The follow-up query targets `news`, which returns a URL not seen in round 1.
    ctx = ctx_factory(usd_cap=5.0, registry={
        "kokkai": FakeConn("kokkai", [news_hit()]),
        "academic": FakeConn("academic", []),
        "news": FakeConn("news", [news_hit().model_copy(
            update={"url": "https://www.ft.com/new-one"})]),
    })
    graph = build_graph()
    final = graph.invoke(_state(), context=ctx)
    urls = {h.url for h in final["hits"]}
    assert urls == {"https://www.reuters.com/article/1", "https://www.ft.com/new-one"}


def test_deep_synthesizes_on_the_high_judgement_model(fake_stream, fake_structured, ctx_factory):
    graph = build_graph()
    graph.invoke(_state(), context=ctx_factory(usd_cap=5.0))
    synth = [c for c in fake_stream if c["actor"] == "synthesizer"][0]
    assert synth["model"] == "gpt-5.6-sol"


def test_cancel_during_research_stops_and_marks_state(fake_stream, fake_structured, ctx_factory):
    flag = {"cancelled": False}

    def cancel_check():
        return flag["cancelled"]

    # Cancel arrives after planning: the graph must not keep searching.
    original = fake_structured["calls"]

    class CancellingConn:
        name, disabled = "kokkai", False

        def search(self, q):
            flag["cancelled"] = True
            return [news_hit()]

    ctx = ctx_factory(usd_cap=5.0, cancel_check=cancel_check,
                      registry={"kokkai": CancellingConn(), "academic": FakeConn("academic", [])})
    graph = build_graph()
    final = graph.invoke(_state(), context=ctx)
    assert final["stop_reason"] == "cancelled"
    assert "gap" not in original[1:]        # never reached the gap critic
