"""The trusted-source invariants, pinned end-to-end (M0-b, plan §5.8).

The system's bias toward government/parliamentary records, peer-reviewed work and
official primary material is enforced by DETERMINISTIC code, not by the prompts —
the prompts only help the model arrive there sooner. These tests pin the code:

  #1 plan.py  — STRATEGY_MATRIX fixes up a bad strategy list
  #5 gather.py — triage drops tertiary and caps the selection
  #6 verify.py — an RQ needs ≥2 evidence incl. ≥1 primary/secondary to resolve
  #4 rubric.py — the citation gate deterministically demotes weakly-backed claims

They assert on ARTIFACTS (the plan, the selection, coverage, claims) rather than on
internals, and drive the whole pipeline through one seam, so they survive the
LangGraph port: M1 swaps the seam for `runner.run_research` and M2 relocates the
phase code into nodes — in both cases these assertions must hold unchanged. A
weakening of the trust model therefore fails the suite rather than passing review.
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
from app.research.phases.gather import MAX_SELECTED
from app.research.phases.plan import STRATEGY_MATRIX
from app.research.schemas import BudgetState, ResearchRun, SourceHit


class _Store:
    def __init__(self):
        self.runs, self.evidence, self.claims, self.posts = {}, {}, {}, {}
        self.seq = 0


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


@pytest.fixture
def store(monkeypatch):
    """In-memory Firestore/GCS. `llm` is left for each test to install."""
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
    monkeypatch.setattr(rr_repo, "get_evidence",
                        lambda rid: list(s.evidence.get(rid, {}).values()))
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
    return s


def _install_llm(monkeypatch, store, *, planner, triage, verifier=None):
    """Install a fake LLM; only the actors under test need custom behaviour."""
    def fake_structured(schema, model, system, user, *, budget, run_id, phase, actor,
                        prompt_version="", extra_detail=None):
        if actor == "retriever":
            return schema.model_validate(
                {"queries": [{"query": "refined", "language": "ja"}]})
        if actor == "planner":
            return schema.model_validate(planner)
        if actor == "triage":
            return schema.model_validate(triage(store, run_id))
        if actor == "extractor":
            return schema.model_validate({"excerpt": "…", "quotes": [], "claims": ["事実"],
                                          "stance": "", "isInterpretation": False})
        if actor == "verifier":
            ev_ids = list(store.evidence.get(run_id, {}).keys())
            if verifier is not None:
                return schema.model_validate(verifier(ev_ids))
            return schema.model_validate({"claims": []})
        if actor == "writer":
            return schema.model_validate({"language": "ja", "title": "T", "summary": "S",
                "sections": [{"heading": "h", "claimIds": [], "footnotes": [], "body": "b"}],
                "references": []})
        if actor == "localizer":
            return schema.model_validate({"language": "xx", "title": "T", "summary": "S",
                                          "body": "b", "footnoteCount": 0})
        if actor == "critic":
            return schema.model_validate({"findings": [], "passed": True})
        raise AssertionError(f"unexpected actor {actor}")
    monkeypatch.setattr(llm_mod, "structured", fake_structured)


def _run(store, registry, run_id="rr_inv_01", theme="ある調査テーマ"):
    run = ResearchRun(
        id=run_id, trigger="manual", requestedBy="u@example.com",
        categoryId="geopolitics-history", theme=theme,
        budget=BudgetState(usdCap=10.0), languages=["ja"], canonicalLanguage="ja",
        status="running", phase="plan")
    store.runs[run.id] = run

    def factory(r):
        return RunContext(run=r, budget=Budget(r.budget), registry=registry,
                          fetcher=_FakeFetcher())
    return ResearchHarness(ctx_factory=factory).run(run.id), run


def _keep_all(tier):
    def _triage(store, run_id):
        return {"selections": [{"index": i, "keep": True, "tier": tier, "relevance": 0.9}
                               for i in range(40)]}
    return _triage


# ---- invariant #1: the Source Strategy Matrix has the last word -------------

def test_plan_fixes_invalid_strategies_to_matrix(store, monkeypatch):
    """A planner naming junk (or web-only) connectors cannot redirect the run.

    plan.py keeps only strategies present in the theme class's matrix row and, if
    that leaves nothing, falls back to the row's top 4 — which are the official and
    scholarly connectors. The prompt asks for this ordering; this is what enforces it.
    """
    _install_llm(monkeypatch, store, planner={
        "themeClass": "politics_history", "contested": False,
        "rqs": [
            # every strategy invalid -> falls back to matrix[:4]
            {"id": "rq1", "q": "q1", "strategies": ["blogs", "seo_farm", "not_a_connector"]},
            # partially valid -> only the valid ones survive, order preserved
            {"id": "rq2", "q": "q2", "strategies": ["news", "wikipedia", "kokkai"]},
        ]},
        triage=_keep_all("primary"))

    _run(store, {"kokkai": _FakeConn("kokkai", [_kokkai_hit()])})
    plan = store.runs["rr_inv_01"].plan
    matrix = STRATEGY_MATRIX["politics_history"]

    assert plan.rqs[0].strategies == matrix[:4]
    assert plan.rqs[1].strategies == ["news", "kokkai"]
    for rq in plan.rqs:
        assert all(s in matrix for s in rq.strategies), rq.strategies

    # The fallback must lead with official/scholarly sources, never web-first.
    assert matrix[:4] == ["kokkai", "gov_docs", "books", "academic"]


def test_strategy_matrix_never_leads_with_the_open_web(store):
    """Pure-data guard: web_grounded is never a theme class's first resort.

    Deliberately NOT asserting that an authoritative connector always outranks
    web_grounded — `society_culture` really does put it second (above academic),
    which is a considered product choice for topics whose primary material is the
    open web. Every row still leads with a curated connector and still carries
    authoritative options, which is the property worth pinning.
    """
    authoritative = {"kokkai", "gov_docs", "academic", "ieee", "books"}
    for theme_class, row in STRATEGY_MATRIX.items():
        assert row[0] != "web_grounded", theme_class
        assert "web_grounded" in row, theme_class
        assert set(row) & authoritative, theme_class
    # the one row where the open web outranks scholarly sources, pinned explicitly
    # so a change to it is a deliberate edit rather than a silent drift
    sc = STRATEGY_MATRIX["society_culture"]
    assert sc.index("web_grounded") < sc.index("academic")


# ---- invariant #5: triage drops tertiary and caps the selection -------------

def test_triage_drops_tertiary_and_caps_selection(store, monkeypatch):
    """Tertiary sources are navigation aids: they must never become evidence."""
    _install_llm(monkeypatch, store, planner={
        "themeClass": "politics_history", "contested": False,
        "rqs": [{"id": "rq1", "q": "q1", "strategies": ["kokkai"]}]},
        triage=lambda s, rid: {"selections": [
            # alternate secondary/tertiary across 40 candidates
            {"index": i, "keep": True,
             "tier": "secondary" if i % 2 == 0 else "tertiary", "relevance": 0.9}
            for i in range(40)]})

    many = [_news_hit(i) for i in range(40)]
    ctx, _ = _run(store, {"kokkai": _FakeConn("kokkai", many)})

    assert ctx is not None
    assert len(ctx.selected) <= MAX_SELECTED
    assert all(h.tierHint != "tertiary" for h in ctx.selected)
    # and nothing tertiary reached the evidence store
    assert all(e.tier != "tertiary" for e in store.evidence.get("rr_inv_01", {}).values())


# ---- invariant #6: coverage demands tiered evidence -------------------------

def test_coverage_requires_tiered_evidence_loops_on_tertiary_only(store, monkeypatch):
    """An RQ backed only by weak evidence is NOT resolved — it drives another loop.

    Resolution needs ≥2 evidence records AND ≥1 primary/secondary. A single
    secondary source fails the count; that unresolved RQ is what makes the run
    loop back to gather rather than write on thin material.
    """
    _install_llm(monkeypatch, store, planner={
        "themeClass": "politics_history", "contested": False,
        "rqs": [{"id": "rq1", "q": "q1", "strategies": ["news"]}]},
        triage=lambda s, rid: {"selections": [
            {"index": 0, "keep": True, "tier": "secondary", "relevance": 0.9}]})

    # exactly one source -> one evidence record -> below MIN_EVIDENCE_PER_RQ
    ctx, run = _run(store, {"news": _FakeConn("news", [_news_hit(0)])})

    assert ctx is not None
    assert len(store.evidence["rr_inv_01"]) == 1
    assert ctx.coverage is not None
    rq_cov = {c.rqId: c for c in ctx.coverage.rqCoverage}
    assert rq_cov["rq1"].resolved is False
    # the loop ceiling is what eventually stops it, not a lowered evidence bar
    assert run.loops >= 1


# ---- invariant #4: the citation gate demotes weakly-backed claims -----------

def test_weak_claims_render_demoted(store, monkeypatch):
    """A "corroborated" verdict on one weak source is still NOT an assertion.

    render_as() only yields "assertion" when the citation gate passes: one primary
    scoring ≥60, or two INDEPENDENT secondaries. A lone secondary web source fails
    it, so the claim is demoted regardless of what the verifier LLM asserted — the
    model cannot talk its way past the gate.
    """
    _install_llm(monkeypatch, store, planner={
        "themeClass": "society_culture", "contested": False,
        "rqs": [{"id": "rq1", "q": "q1", "strategies": ["news"]}]},
        triage=lambda s, rid: {"selections": [
            {"index": 0, "keep": True, "tier": "secondary", "relevance": 0.9}]},
        verifier=lambda ev_ids: {"claims": [
            {"claimId": "cl_weak", "rqId": "rq1", "text": "弱い根拠の主張",
             "evidenceIds": ev_ids[:1], "verdict": "corroborated",
             "stance": "", "isInterpretation": False, "confidence": 0.99}]})

    ctx, _ = _run(store, {"news": _FakeConn("news", [_blog_hit()])})

    assert ctx is not None
    weak = [c for c in ctx.claims if c.claimId == "cl_weak"]
    assert weak, "the verifier's claim should have been recorded"
    assert weak[0].renderAs != "assertion"
    assert weak[0].renderAs == "opinion_report"


# --------------------------------------------------------------------------- #
# hits                                                                          #
# --------------------------------------------------------------------------- #

def _kokkai_hit():
    return SourceHit(
        title="第102回国会 参議院内閣委員会 第3号", url="https://kokkai.ndl.go.jp/txt/1",
        identifiers={"kokkaiIssueId": "110214889X00319881213"}, snippet="責任という言葉",
        publishedAt="1988-12-13", sourceType="parliamentary_record", tierHint="primary",
        connector="kokkai", contentText="答弁記録。" * 30)


def _news_hit(i: int):
    return SourceHit(
        title=f"報道 {i}", url=f"https://www.reuters.com/article/{i}", snippet="…",
        publishedAt="2020-01-01", sourceType="quality_news", tierHint="secondary",
        connector="news")


def _blog_hit():
    """A general web page — the weakest thing that can still survive triage."""
    return SourceHit(
        title="個人ブログの解説", url="https://example-blog.test/post/1", snippet="…",
        publishedAt="2024-01-01", sourceType="web", connector="news")
