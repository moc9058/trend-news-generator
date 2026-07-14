"""P3/P4: golden plan→review integration test (design §8.1 L2).

Runs the full Research Harness end-to-end with the LLM, connectors, fetcher, GCS
and Firestore all mocked. Asserts the DoD: a 3-language draft Post(format=report)
is produced, citecheck passes, contested coverage has ≥2 stances, and the science
golden's arXiv:1706.03762 flows into evidence with the right tier.
"""

import pytest

import app.repo.posts as posts_repo
import app.repo.research as rr_repo
import app.research.llm as llm_mod
import app.utils.gcs as gcs_mod
from app.research.budget import Budget
from app.research.context import RunContext
from app.research.fetch.fetcher import FetchResult
from app.research.harness import ResearchHarness
from app.research.schemas import BudgetState, ResearchRun, SourceHit


# --------------------------------------------------------------------------- #
# In-memory store + fakes                                                     #
# --------------------------------------------------------------------------- #

class _Store:
    def __init__(self):
        self.runs, self.evidence, self.claims, self.posts = {}, {}, {}, {}
        self.seq = 0


@pytest.fixture
def store(monkeypatch):
    s = _Store()

    monkeypatch.setattr(rr_repo, "get", lambda rid: s.runs.get(rid))
    monkeypatch.setattr(rr_repo, "save", lambda run: s.runs.__setitem__(run.id, run))
    monkeypatch.setattr(rr_repo, "update_fields", lambda rid, fields: None)
    monkeypatch.setattr(rr_repo, "heartbeat", lambda rid, now=None: None)

    def _set_status(rid, status, **extra):
        if rid in s.runs:
            s.runs[rid].status = status
    monkeypatch.setattr(rr_repo, "set_status", _set_status)

    def _ev_create(rid, ev):
        d = s.evidence.setdefault(rid, {})
        if ev.evidenceId in d:
            return False
        d[ev.evidenceId] = ev
        return True
    monkeypatch.setattr(rr_repo, "evidence_create_if_absent", _ev_create)
    monkeypatch.setattr(rr_repo, "get_evidence", lambda rid: list(s.evidence.get(rid, {}).values()))
    monkeypatch.setattr(rr_repo, "upsert_claim",
                        lambda rid, c: s.claims.setdefault(rid, {}).__setitem__(c.claimId, c))
    monkeypatch.setattr(rr_repo, "get_claims", lambda rid: list(s.claims.get(rid, {}).values()))
    monkeypatch.setattr(rr_repo, "append_event", lambda rid, ev: None)

    def _post_create(post):
        s.seq += 1
        pid = f"post_{s.seq}"
        s.posts[pid] = post
        return pid
    monkeypatch.setattr(posts_repo, "create", _post_create)
    monkeypatch.setattr(gcs_mod, "upload_bytes", lambda path, data, mime: path)

    # fake LLM: dispatch on actor, building the phase's schema from a fixture dict.
    counter = {"n": 0}

    def fake_structured(schema, model, system, user, *, budget, run_id, phase, actor,
                        prompt_version="", extra_detail=None):
        if actor == "retriever":
            # query refinement (gather retrieval leg): one refined query
            return schema.model_validate({"queries": [{"query": "refined query", "language": "ja"}]})
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
            ev_ids = list(s.evidence.get(run_id, {}).keys())
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
            ev_ids = list(s.evidence.get(run_id, {}).keys())
            return schema.model_validate({"language": "ja", "title": "調査報告書", "summary": "要約",
                "sections": [{"heading": "背景", "claimIds": ["cl_1_a"], "footnotes": [1],
                              "body": "本文[1]"}], "references": ev_ids})
        if actor == "localizer":
            return schema.model_validate({"language": "xx", "title": "T", "summary": "S",
                "body": "localized body [1]",
                "footnoteCount": len(s.evidence.get(run_id, {}))})
        if actor == "critic":
            return schema.model_validate({"findings": [], "passed": True})
        raise AssertionError(f"unexpected actor {actor}")

    monkeypatch.setattr(llm_mod, "structured", fake_structured)
    return s


class _FakeConn:
    def __init__(self, name, hits):
        self.name, self._hits, self.disabled = name, hits, False

    def search(self, q):
        return [h.model_copy(deep=True) for h in self._hits]


class _FakeFetcher:
    def fetch(self, url):
        return FetchResult(
            data=(f"Substantial source material about the topic, from {url}, "
                  "with several sentences of analysis.").encode("utf-8"),
            mimeType="text/plain", finalUrl=url)


def _kokkai_hit():
    return SourceHit(
        title="第102回国会 参議院内閣委員会 第3号", url="https://kokkai.ndl.go.jp/txt/1",
        identifiers={"kokkaiIssueId": "110214889X00319881213"}, snippet="責任という言葉",
        publishedAt="1988-12-13", sourceType="parliamentary_record", tierHint="primary",
        connector="kokkai", contentText="「天皇の戦争責任」に関する答弁記録。" * 30)


def _academic_hit():
    # stands in for §8.1's Transformer golden: arXiv:1706.03762 must reach evidence.
    return SourceHit(
        title="Attention Is All You Need", url="https://arxiv.org/abs/1706.03762",
        identifiers={"arxivId": "1706.03762", "doi": "10.48550/arXiv.1706.03762"},
        publishedAt="2017-06-12", venue="arXiv", sourceType="preprint", tierHint="primary",
        connector="academic", citationCount=150000)


def _news_hit():
    return SourceHit(
        title="戦後責任論に関する報道", url="https://www.reuters.com/article/1",
        snippet="…", publishedAt="2020-01-01", sourceType="quality_news",
        tierHint="secondary", connector="news")


def _factory(run):
    return RunContext(
        run=run, budget=Budget(run.budget),
        registry={
            "kokkai": _FakeConn("kokkai", [_kokkai_hit()]),
            "academic": _FakeConn("academic", [_academic_hit()]),
            "news": _FakeConn("news", [_news_hit()]),
        },
        fetcher=_FakeFetcher())


# --------------------------------------------------------------------------- #

def test_golden_full_run_produces_trilingual_report_post(store):
    run = ResearchRun(
        id="rr_20260801_test01", trigger="manual", requestedBy="u@example.com",
        categoryId="geopolitics-history", theme="天皇の戦争への責任",
        budget=BudgetState(usdCap=10.0), languages=["ja", "ko", "en"],
        canonicalLanguage="ja", status="running", phase="plan")
    store.runs[run.id] = run

    ctx = ResearchHarness(ctx_factory=_factory).run(run.id)

    # reached handoff → awaiting_review, Post created
    assert ctx is not None
    assert store.runs[run.id].status == "awaiting_review"
    assert store.runs[run.id].postId and ctx.postId == store.runs[run.id].postId
    post = store.posts[ctx.postId]
    assert post.format.value == "report" and post.researchRunId == run.id

    # three languages present in the draft Post
    assert set(post.localizations.keys()) == {"ja", "ko", "en"}
    assert post.localizations["ja"].title == "調査報告書"

    # evidence: kokkai (primary) + academic arXiv + news, with arXiv:1706.03762 present
    ev = store.evidence[run.id]
    assert len(ev) == 3
    arxiv = [e for e in ev.values() if e.identifiers.get("arxivId") == "1706.03762"]
    assert arxiv and arxiv[0].tier == "primary"
    kokkai = [e for e in ev.values() if e.sourceType == "parliamentary_record"]
    assert kokkai and kokkai[0].tier == "primary"

    # contested coverage: ≥2 stances represented across claims
    stances = {c.stance for c in ctx.claims if c.stance}
    assert {"positionA", "positionB"} <= stances

    # citecheck 100% (all cited evidenceIds exist) + 3 languages consistent + passed
    assert ctx.audit is not None
    assert ctx.audit.citeCheckPassRate == 1.0
    assert ctx.audit.triLanguageConsistent is True
    assert ctx.audit.passed is True

    # coverage finalized (both RQs have ≥2 evidence) — no unresolved loop needed
    assert ctx.coverage is not None and ctx.coverage.decision == "finalize"


def test_golden_run_resumes_from_legacy_phase_name(store):
    # A pre-consolidation run stored with phase="R0" is bridged by the compat
    # shim (LEGACY_PHASE_MAP) and completes end-to-end on the 6-phase order.
    run = ResearchRun(
        id="rr_legacy", trigger="manual", theme="天皇の戦争への責任",
        budget=BudgetState(usdCap=10.0), languages=["ja", "ko", "en"],
        canonicalLanguage="ja", status="running", phase="R0")
    assert run.phase == "plan"  # shim applied at model build
    store.runs[run.id] = run

    ctx = ResearchHarness(ctx_factory=_factory).run(run.id)
    assert ctx is not None
    assert store.runs[run.id].status == "awaiting_review"
    assert store.runs[run.id].postId


def test_verify_loops_back_to_gather_until_loop_ceiling(store):
    # rq2's connectors never return hits → rq2 stays unresolved → the verify
    # coverage leg loops back to gather until research_max_loops (2), then
    # finalizes with the gap surfaced (§6.4 — never silently dropped).
    class _Rq1OnlyConn(_FakeConn):
        def search(self, q):
            return super().search(q) if q.rqId == "rq1" else []

    def factory(run):
        return RunContext(
            run=run, budget=Budget(run.budget),
            registry={
                "kokkai": _Rq1OnlyConn("kokkai", [_kokkai_hit()]),
                "academic": _Rq1OnlyConn("academic", [_academic_hit()]),
                "news": _Rq1OnlyConn("news", [_news_hit()]),
            },
            fetcher=_FakeFetcher())

    run = ResearchRun(
        id="rr_loop", trigger="manual", theme="天皇の戦争への責任",
        budget=BudgetState(usdCap=10.0), languages=["ja"],
        canonicalLanguage="ja", status="running", phase="plan")
    store.runs[run.id] = run

    ctx = ResearchHarness(ctx_factory=factory).run(run.id)
    assert ctx is not None
    assert store.runs[run.id].loops == 2  # looped twice, then hit the ceiling
    assert ctx.coverage is not None and ctx.coverage.decision == "finalize"
    unresolved = [rq for rq in ctx.coverage.rqCoverage if not rq.resolved]
    assert [rq.rqId for rq in unresolved] == ["rq2"]
    assert store.runs[run.id].status == "awaiting_review"  # still handed off


def test_review_revise_loops_back_to_write_once(store, monkeypatch):
    # First critic verdict fails → review loops back to write for one corrective
    # rewrite; second verdict passes → handoff runs.
    import app.research.llm as llm

    orig = llm.structured
    calls = {"critic": 0, "writer": 0}

    def wrapper(schema, model, system, user, **kw):
        actor = kw.get("actor")
        if actor == "writer":
            calls["writer"] += 1
        if actor == "critic":
            calls["critic"] += 1
            if calls["critic"] == 1:
                return schema.model_validate({"findings": [
                    {"kind": "unsupported_assertion", "location": "s1",
                     "detail": "no citation", "action": "delete"}], "passed": False})
        return orig(schema, model, system, user, **kw)
    monkeypatch.setattr(llm, "structured", wrapper)

    run = ResearchRun(
        id="rr_revise", trigger="manual", theme="天皇の戦争への責任",
        budget=BudgetState(usdCap=10.0), languages=["ja", "ko", "en"],
        canonicalLanguage="ja", status="running", phase="plan")
    store.runs[run.id] = run

    ctx = ResearchHarness(ctx_factory=_factory).run(run.id)
    assert ctx is not None
    assert calls == {"critic": 2, "writer": 2}  # one corrective rewrite
    assert ctx.revisions == 1
    assert store.runs[run.id].status == "awaiting_review"
    assert store.runs[run.id].postId


def test_gather_falls_back_to_raw_rq_when_refinement_fails(store, monkeypatch):
    # Query-refinement LLM failure must degrade to the raw RQ text and still
    # search the connectors — never fail the gather phase.
    import app.research.llm as llm

    orig = llm.structured

    def wrapper(schema, model, system, user, **kw):
        if kw.get("actor") == "retriever":
            raise llm.ResearchLLMError("refinement broke")
        return orig(schema, model, system, user, **kw)
    monkeypatch.setattr(llm, "structured", wrapper)
    # gather catches llm.ResearchLLMError via the module attribute; keep it intact
    queries_seen = []

    class _RecordingConn(_FakeConn):
        def search(self, q):
            queries_seen.append(q.query)
            return super().search(q)

    def factory(run):
        return RunContext(
            run=run, budget=Budget(run.budget),
            registry={
                "kokkai": _RecordingConn("kokkai", [_kokkai_hit()]),
                "academic": _RecordingConn("academic", [_academic_hit()]),
                "news": _RecordingConn("news", [_news_hit()]),
            },
            fetcher=_FakeFetcher())

    run = ResearchRun(
        id="rr_fallback", trigger="manual", theme="天皇の戦争への責任",
        budget=BudgetState(usdCap=10.0), languages=["ja"],
        canonicalLanguage="ja", status="running", phase="plan")
    store.runs[run.id] = run

    ResearchHarness(ctx_factory=factory).run(run.id)
    # raw RQ texts were used as queries (fixture RQs from the planner fake)
    assert "戦前の天皇の法的権限" in queries_seen
    assert store.runs[run.id].status == "awaiting_review"
    assert store.evidence[run.id]  # evidence still produced


def test_golden_citecheck_flags_hallucinated_citation(store):
    # A writer that cites a non-existent evidenceId must fail citecheck.
    from app.research.fetch import citecheck
    from app.research.schemas import EvidenceRecord, ReportDraft
    ev = [EvidenceRecord(evidenceId="real1"), EvidenceRecord(evidenceId="real2")]
    good = ReportDraft(references=["real1", "real2"])
    bad = ReportDraft(references=["real1", "ghost99"])
    assert citecheck.verify_quotes(good, ev).passed is True
    audit = citecheck.verify_quotes(bad, ev)
    assert audit.passed is False and audit.citeCheckPassRate == 0.5
    assert audit.findings[0].kind == "hallucinated_citation"
