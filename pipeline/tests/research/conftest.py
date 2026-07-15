"""Shared fakes for the research graph tests (design §8.1 L2).

Collected here so the golden test and the trusted-source invariants drive the
pipeline through the SAME fakes and the SAME seam. That is what makes them a
parity gate across the LangGraph migration: M1 swapped the harness for
runner.run_research and M2 relocated the phase code into fan-out nodes, but as long
as these fixtures and the assertions on top of them stay put, "the new thing does
what the old thing did" is a property the suite checks rather than a claim.
"""

import pytest
from langgraph.checkpoint.memory import InMemorySaver

import app.repo.posts as posts_repo
import app.repo.research as rr_repo
import app.research.llm as llm_mod
import app.utils.gcs as gcs_mod
from app.research.budget import Budget
from app.research.fetch.fetcher import FetchResult
from app.research.graph.builder import build_graph
from app.research.graph.context import ResearchRuntimeContext
from app.research.graph.runner import run_research
from app.research.schemas import SourceHit


class Store:
    """In-memory stand-in for the run's Firestore documents."""

    def __init__(self):
        self.runs, self.evidence, self.claims, self.posts = {}, {}, {}, {}
        self.events: list = []
        self.seq = 0


@pytest.fixture
def store(monkeypatch):
    s = Store()

    monkeypatch.setattr(rr_repo, "get", lambda rid: s.runs.get(rid))
    monkeypatch.setattr(rr_repo, "save", lambda run: s.runs.__setitem__(run.id, run))
    monkeypatch.setattr(rr_repo, "heartbeat", lambda rid, now=None: None)

    def _update_fields(rid, fields):
        run = s.runs.get(rid)
        if run is None:
            return
        for k, v in fields.items():
            if k == "budget":
                continue  # the run holds the live BudgetState object
            setattr(run, k, v)
    monkeypatch.setattr(rr_repo, "update_fields", _update_fields)

    def _set_status(rid, status, **extra):
        # Mirrors the real set_status = update_fields({"status": ..., **extra});
        # `extra` matters — the approval pause sets phase="gather" through it.
        _update_fields(rid, {"status": status, **extra})
    monkeypatch.setattr(rr_repo, "set_status", _set_status)

    def _ev_create(rid, ev):
        d = s.evidence.setdefault(rid, {})
        if ev.evidenceId in d:
            return False
        d[ev.evidenceId] = ev
        return True
    monkeypatch.setattr(rr_repo, "evidence_create_if_absent", _ev_create)
    monkeypatch.setattr(rr_repo, "get_evidence",
                        lambda rid: list(s.evidence.get(rid, {}).values()))
    monkeypatch.setattr(rr_repo, "upsert_claim",
                        lambda rid, c: s.claims.setdefault(rid, {}).__setitem__(c.claimId, c))
    monkeypatch.setattr(rr_repo, "get_claims", lambda rid: list(s.claims.get(rid, {}).values()))
    monkeypatch.setattr(rr_repo, "append_event", lambda rid, ev: s.events.append((rid, ev)))

    def _post_create(post):
        s.seq += 1
        pid = f"post_{s.seq}"
        s.posts[pid] = post
        return pid
    monkeypatch.setattr(posts_repo, "create", _post_create)
    monkeypatch.setattr(gcs_mod, "upload_bytes", lambda path, data, mime: path)
    return s


# --------------------------------------------------------------------------- #
# Fake collaborators                                                           #
# --------------------------------------------------------------------------- #

class FakeConn:
    def __init__(self, name, hits):
        self.name, self._hits, self.disabled = name, hits, False

    def search(self, q):
        return [h.model_copy(deep=True) for h in self._hits]


class FakeFetcher:
    def fetch(self, url):
        return FetchResult(
            data=(f"Substantial source material about the topic, from {url}, "
                  "with several sentences of analysis.").encode("utf-8"),
            mimeType="text/plain", finalUrl=url)


def kokkai_hit():
    return SourceHit(
        title="第102回国会 参議院内閣委員会 第3号", url="https://kokkai.ndl.go.jp/txt/1",
        identifiers={"kokkaiIssueId": "110214889X00319881213"}, snippet="責任という言葉",
        publishedAt="1988-12-13", sourceType="parliamentary_record", tierHint="primary",
        connector="kokkai", contentText="「天皇の戦争責任」に関する答弁記録。" * 30)


def academic_hit():
    # stands in for §8.1's Transformer golden: arXiv:1706.03762 must reach evidence.
    return SourceHit(
        title="Attention Is All You Need", url="https://arxiv.org/abs/1706.03762",
        identifiers={"arxivId": "1706.03762", "doi": "10.48550/arXiv.1706.03762"},
        publishedAt="2017-06-12", venue="arXiv", sourceType="preprint", tierHint="primary",
        connector="academic", citationCount=150000)


def news_hit():
    return SourceHit(
        title="戦後責任論に関する報道", url="https://www.reuters.com/article/1",
        snippet="…", publishedAt="2020-01-01", sourceType="quality_news",
        tierHint="secondary", connector="news")


def default_registry():
    return {
        "kokkai": FakeConn("kokkai", [kokkai_hit()]),
        "academic": FakeConn("academic", [academic_hit()]),
        "news": FakeConn("news", [news_hit()]),
    }


# --------------------------------------------------------------------------- #
# The seam                                                                     #
# --------------------------------------------------------------------------- #

def drive(run, registry=None, *, saver=None, graph=None):
    """Run `run` through the real graph with fake collaborators.

    THE seam the whole parity strategy rests on: production and tests execute the
    same nodes, the same routing and the same checkpointer contract — only the
    connectors, fetcher, LLM and Firestore are fakes. Returns (final_state, graph)
    so a test can resume the same thread or inspect what survived.
    """
    graph = graph or build_graph(saver or InMemorySaver())
    budget = Budget(run.budget)
    ctx = ResearchRuntimeContext(
        budget=budget, registry=registry if registry is not None else default_registry(),
        fetcher=FakeFetcher(), run_id=run.id)
    final = run_research(run, graph=graph, context=ctx)
    return final, graph


# --------------------------------------------------------------------------- #
# Fake LLM                                                                     #
# --------------------------------------------------------------------------- #

def install_fake_llm(monkeypatch, store):
    """Actor-dispatched fake for llm.structured, mirroring the golden fixtures.

    M2 runs the graph's workers on real threads (max_concurrency=4), so this fake
    is exactly as concurrent as production LLM calls would be — the counter is
    locked, and everything else reads immutable inputs or GIL-atomic dict ops.
    """
    import threading

    counter = {"n": 0}
    counter_lock = threading.Lock()

    def fake_structured(schema, model, system, user, *, budget, run_id, phase, actor,
                        prompt_version="", extra_detail=None):
        if actor == "retriever":
            return schema.model_validate(
                {"queries": [{"query": "refined query", "language": "ja"}]})
        if actor == "planner":
            return schema.model_validate({"themeClass": "politics_history", "contested": True,
                "rqs": [{"id": "rq1", "q": "戦前の天皇の法的権限", "strategies": ["kokkai", "academic"]},
                        {"id": "rq2", "q": "戦後の責任論の扱い", "strategies": ["kokkai", "news"]}]})
        if actor == "triage":
            # stable retrieval order is [kokkai, academic(arXiv), news]; the first
            # two are primary sources, news is secondary.
            return schema.model_validate({"selections": [
                {"index": i, "keep": True, "tier": "primary" if i < 2 else "secondary",
                 "relevance": 0.9} for i in range(8)]})
        if actor == "extractor":
            return schema.model_validate({"excerpt": "…", "quotes": [
                {"quoteId": "q1", "text": "「責任」", "locator": {"charStart": 0, "charEnd": 4}}],
                "claims": ["事実"], "stance": "positionA", "isInterpretation": False})
        if actor == "verifier":
            ev_ids = list(store.evidence.get(run_id, {}).keys())
            with counter_lock:
                counter["n"] += 1
                n = counter["n"]
            return schema.model_validate({"claims": [
                {"claimId": f"cl_{n}_a", "rqId": "rq", "text": "断定できる事実",
                 "evidenceIds": ev_ids[:1], "verdict": "corroborated",
                 "stance": "positionA", "isInterpretation": False, "confidence": 0.95},
                {"claimId": f"cl_{n}_b", "rqId": "rq", "text": "異なる解釈",
                 "evidenceIds": ev_ids[:1], "verdict": "single_source",
                 "stance": "positionB", "isInterpretation": True, "confidence": 0.6}]})
        if actor == "writer":
            ev_ids = list(store.evidence.get(run_id, {}).keys())
            return schema.model_validate({"language": "ja", "title": "調査報告書", "summary": "要約",
                "sections": [{"heading": "背景", "claimIds": ["cl_1_a"], "footnotes": [1],
                              "body": "本文[1]"}], "references": ev_ids})
        if actor == "localizer":
            return schema.model_validate({"language": "xx", "title": "T", "summary": "S",
                "body": "localized body [1]",
                "footnoteCount": len(store.evidence.get(run_id, {}))})
        if actor == "critic":
            return schema.model_validate({"findings": [], "passed": True})
        raise AssertionError(f"unexpected actor {actor}")

    monkeypatch.setattr(llm_mod, "structured", fake_structured)
    return fake_structured


@pytest.fixture
def fake_llm(monkeypatch, store):
    install_fake_llm(monkeypatch, store)
    return store
