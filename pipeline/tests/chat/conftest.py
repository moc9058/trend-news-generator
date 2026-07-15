"""Shared fakes for the chat graph tests (tests/research/test_harness_golden.py idiom)."""

from datetime import datetime, timedelta, timezone

import pytest

import app.chat.graph as graph_mod
import app.chat.stream_llm as stream_mod
import app.research.llm as llm_mod
from app.chat.graph import ChatRunContext
from app.research.budget import Budget
from app.research.fetch.fetcher import FetchResult
from app.research.schemas import BudgetState, SourceHit


class FakeConn:
    def __init__(self, name, hits):
        self.name, self._hits, self.disabled = name, hits, False

    def search(self, q):
        return [h.model_copy(deep=True) for h in self._hits]


class FakeFetcher:
    def __init__(self):
        self.calls = []

    def fetch(self, url):
        self.calls.append(url)
        return FetchResult(
            data=(f"Substantial body text about the question, from {url}. " * 20).encode("utf-8"),
            mimeType="text/plain", finalUrl=url)


def kokkai_hit():
    return SourceHit(
        title="第208回国会 衆議院予算委員会", url="https://kokkai.ndl.go.jp/txt/1",
        snippet="答弁", publishedAt="2022-02-01", sourceType="parliamentary_record",
        tierHint="primary", connector="kokkai",
        contentText="国会での答弁記録。" * 50)


def academic_hit():
    return SourceHit(
        title="Attention Is All You Need", url="https://arxiv.org/abs/1706.03762",
        identifiers={"arxivId": "1706.03762"}, publishedAt="2017-06-12",
        venue="arXiv", sourceType="preprint", tierHint="primary", connector="academic")


def news_hit():
    return SourceHit(
        title="関連する報道", url="https://www.reuters.com/article/1", snippet="…",
        publishedAt="2024-01-01", sourceType="quality_news", tierHint="secondary",
        connector="news")


@pytest.fixture
def fake_stream(monkeypatch):
    """Replace the OpenAI streaming call; record what each actor was sent."""
    calls = []

    def _stream_chat(*, model, system, messages, budget, on_delta, actor, phase,
                     events=None, should_stop=None):
        calls.append({"model": model, "system": system, "messages": messages,
                      "actor": actor, "phase": phase})
        text = f"answer from {actor}"
        for token in text.split(" "):
            on_delta(token + " ")
            if should_stop is not None and should_stop():
                break
        budget.charge_usd(0.01)
        if events is not None:
            events.append({"actor": actor, "costUsd": 0.01, "tokensIn": 10,
                           "tokensOut": 5, "model": model})
        from app.models import TokenUsage
        return text, TokenUsage(inputTokens=10, outputTokens=5, costUsd=0.01)

    monkeypatch.setattr(graph_mod, "stream_chat", _stream_chat)
    monkeypatch.setattr(stream_mod, "stream_chat", _stream_chat, raising=False)
    return calls


@pytest.fixture
def fake_structured(monkeypatch):
    """Dispatch on actor, like the research golden's fake."""
    state = {"gap_decision": "finalize", "calls": []}

    def _structured(schema, model, system, user, *, budget, run_id, phase, actor,
                    prompt_version="", extra_detail=None, event_sink=None):
        state["calls"].append(actor)
        budget.charge_usd(0.005)
        if event_sink is not None:
            event_sink({"actor": actor, "costUsd": 0.005, "tokensIn": 5,
                        "tokensOut": 2, "model": model})
        if actor == "planner":
            return schema.model_validate({
                "themeClass": "politics_history",
                "queries": [{"query": "q1", "connector": "kokkai", "language": "ja"},
                            {"query": "q2", "connector": "academic", "language": "en"}],
                "rationale": "because"})
        if actor == "selector":
            return schema.model_validate({"selections": [
                {"index": i, "keep": True, "relevance": 1.0 - i * 0.1} for i in range(3)]})
        if actor == "gap":
            if state["gap_decision"] == "loop":
                return schema.model_validate({
                    "decision": "loop", "missing": ["more on X"],
                    "followupQueries": [{"query": "q3", "connector": "news", "language": "ja"}]})
            return schema.model_validate({"decision": "finalize", "missing": [],
                                          "followupQueries": []})
        raise AssertionError(f"unexpected actor {actor}")

    monkeypatch.setattr(llm_mod, "structured", _structured)
    monkeypatch.setattr(graph_mod.llm, "structured", _structured)
    return state


@pytest.fixture
def ctx_factory(fake_settings):
    def _make(depth="quick", cancel_check=None, registry=None, fetcher=None,
              deadline=None, usd_cap=1.0, fetch_cap=10):
        return ChatRunContext(
            settings=fake_settings,
            budget=Budget(BudgetState(usdCap=usd_cap, fetchCap=fetch_cap)),
            registry=registry if registry is not None else {
                "kokkai": FakeConn("kokkai", [kokkai_hit()]),
                "academic": FakeConn("academic", [academic_hit()]),
                "news": FakeConn("news", [news_hit()]),
            },
            fetcher=fetcher or FakeFetcher(),
            cancel_check=cancel_check,
            deadline=deadline or datetime.now(timezone.utc) + timedelta(minutes=5))
    return _make


class _Settings:
    chat_model = "gpt-5.6-sol"
    chat_research_model = "gpt-5.6-terra"
    chat_fast_model = "gpt-5.6-luna"
    chat_budget_quick_usd = 0.7
    chat_budget_deep_usd = 3.0
    chat_max_fetches_quick = 6
    chat_max_fetches_deep = 14
    chat_history_max_messages = 40
    chat_wall_clock_quick_min = 3
    chat_wall_clock_deep_min = 10


@pytest.fixture
def fake_settings():
    return _Settings()
