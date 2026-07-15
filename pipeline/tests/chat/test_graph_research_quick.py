"""quick research: plan → search → select → read → synthesize, no gap loop."""

from datetime import datetime, timedelta, timezone

from app.chat.graph import build_graph
from app.chat.schemas import ChatDepth, ChatMode

from .conftest import FakeConn, kokkai_hit, news_hit


def _state(**kw):
    return {"thread_id": "ct_1", "assistant_message_id": "m1",
            "mode": ChatMode.research.value, "depth": ChatDepth.quick.value,
            "user_input": "What did the Diet say about this?", "history": [], **kw}


def test_quick_runs_full_pipeline_and_cites_sources(fake_stream, fake_structured, ctx_factory):
    graph = build_graph()
    final = graph.invoke(_state(), context=ctx_factory())

    # quick plans but never selects (no LLM select) and never gap-checks.
    assert fake_structured["calls"] == ["planner"]
    assert final["answer"] == "answer from synthesizer"
    assert [s.n for s in final["sources"]] == [1, 2]
    # Numbering is dense and 1-based, and matches what was read.
    assert [r.n for r in final["readings"]] == [1, 2]


def test_quick_emits_progress_stages_in_order(fake_stream, fake_structured, ctx_factory):
    graph = build_graph()
    chunks = list(graph.stream(_state(), context=ctx_factory(), stream_mode="custom"))
    stages = [c["data"]["stage"] for c in chunks if c["type"] == "status"]
    assert stages[0] == "planning"
    assert "searching" in stages
    assert "selecting" in stages
    assert "reading" in stages
    assert stages[-1] == "synthesizing"
    # sources are announced before the answer streams
    types = [c["type"] for c in chunks]
    assert types.index("sources") < types.index("token")


def test_quick_dedupes_same_url_across_connectors(fake_stream, fake_structured, ctx_factory):
    # Same article surfaced by two connectors, one with a tracking param and www.
    dup = news_hit()
    dup.url = "https://www.reuters.com/article/1?utm_source=x"
    ctx = ctx_factory(registry={
        "kokkai": FakeConn("kokkai", [news_hit()]),
        "academic": FakeConn("academic", [dup]),
    })
    graph = build_graph()
    final = graph.invoke(_state(), context=ctx)
    assert len(final["hits"]) == 1


def test_quick_orders_primary_before_secondary(fake_stream, fake_structured, ctx_factory):
    ctx = ctx_factory(registry={
        "kokkai": FakeConn("kokkai", [news_hit()]),        # secondary
        "academic": FakeConn("academic", [kokkai_hit()]),  # primary
    })
    graph = build_graph()
    final = graph.invoke(_state(), context=ctx)
    assert [r.tier for r in final["readings"]] == ["primary", "secondary"]


def test_kokkai_content_is_used_without_fetching(fake_stream, fake_structured, ctx_factory):
    from .conftest import FakeFetcher
    fetcher = FakeFetcher()
    ctx = ctx_factory(registry={"kokkai": FakeConn("kokkai", [kokkai_hit()])}, fetcher=fetcher)
    graph = build_graph()
    final = graph.invoke(_state(), context=ctx)
    assert fetcher.calls == []                       # contentText short-circuits the fetch
    assert "国会での答弁記録" in final["readings"][0].text


def test_synthesize_prompt_carries_numbered_sources(fake_stream, fake_structured, ctx_factory):
    graph = build_graph()
    graph.invoke(_state(), context=ctx_factory())
    synth = [c for c in fake_stream if c["actor"] == "synthesizer"][0]
    body = synth["messages"][-1]["content"]
    assert "[1]" in body and "[2]" in body
    assert "untrusted data" in synth["system"].lower()
    assert synth["model"] == "gpt-5.6-terra"          # quick synthesizes on terra


def test_budget_exhaustion_short_circuits_to_synthesize(fake_stream, fake_structured, ctx_factory):
    ctx = ctx_factory(usd_cap=0.004)   # the planner call alone overruns this
    graph = build_graph()
    final = graph.invoke(_state(), context=ctx)
    assert final["stop_reason"] == "budget"
    assert final.get("readings", []) == []   # read never ran, so the key is absent
    assert final["answer"] == "answer from synthesizer"   # degraded, not an error


def test_deadline_short_circuits_to_synthesize(fake_stream, fake_structured, ctx_factory):
    ctx = ctx_factory(deadline=datetime.now(timezone.utc) - timedelta(seconds=1))
    graph = build_graph()
    final = graph.invoke(_state(), context=ctx)
    assert final["stop_reason"] == "deadline"
    assert final["answer"] == "answer from synthesizer"


def test_no_sources_found_still_answers_and_says_so(fake_stream, fake_structured, ctx_factory):
    ctx = ctx_factory(registry={})   # every planned connector missing
    graph = build_graph()
    final = graph.invoke(_state(), context=ctx)
    assert final["sources"] == []
    note = [c for c in fake_stream if c["actor"] == "synthesizer"][0]["messages"][-1]["content"]
    assert "could not find sources" in note


def test_connector_failure_is_non_fatal(fake_stream, fake_structured, ctx_factory):
    class Boom:
        name, disabled = "kokkai", False

        def search(self, q):
            raise RuntimeError("upstream down")

    ctx = ctx_factory(registry={"kokkai": Boom(),
                                "academic": FakeConn("academic", [kokkai_hit()])})
    graph = build_graph()
    final = graph.invoke(_state(), context=ctx)
    assert len(final["readings"]) == 1     # the healthy connector still contributed
