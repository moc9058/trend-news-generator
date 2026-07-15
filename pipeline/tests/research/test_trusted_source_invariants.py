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

import app.research.llm as llm_mod
from app.research.phases.gather import MAX_SELECTED
from app.research.phases.plan import STRATEGY_MATRIX
from app.research.schemas import BudgetState, ResearchRun, SourceHit
from tests.research.conftest import FakeConn, drive


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
    """Drive one run through the graph. M1 moved this seam off ResearchHarness;
    every assertion below stayed exactly as it was, which is the parity claim."""
    run = ResearchRun(
        id=run_id, trigger="manual", requestedBy="u@example.com",
        categoryId="geopolitics-history", theme=theme,
        budget=BudgetState(usdCap=10.0), languages=["ja"], canonicalLanguage="ja",
        status="running", phase="plan")
    store.runs[run.id] = run
    final, _ = drive(run, registry)
    return final, run


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

    _run(store, {"kokkai": FakeConn("kokkai", [_kokkai_hit()])})
    plan = store.runs["rr_inv_01"].plan
    matrix = STRATEGY_MATRIX["politics_history"]

    # rq1's strategies were all invalid -> matrix[:4], plus the deep_research
    # assist that plan.py appends to the first RQ only (§4.3).
    assert plan.rqs[0].strategies == matrix[:4] + ["deep_research"]
    assert plan.rqs[1].strategies == ["news", "kokkai"]
    # Nothing the planner invented survives: only matrix connectors, and the one
    # assist leg the code itself adds.
    for rq in plan.rqs:
        assert all(s in matrix or s == "deep_research" for s in rq.strategies), rq.strategies

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
    final, _ = _run(store, {"kokkai": FakeConn("kokkai", many)})

    assert len(final["selected"]) <= MAX_SELECTED
    assert all(h.tierHint != "tertiary" for h in final["selected"])
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
    final, run = _run(store, {"news": FakeConn("news", [_news_hit(0)])})

    assert len(store.evidence["rr_inv_01"]) == 1
    assert final["coverage"] is not None
    rq_cov = {c.rqId: c for c in final["coverage"].rqCoverage}
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

    final, _ = _run(store, {"news": FakeConn("news", [_blog_hit()])})

    weak = [c for c in final["claims"] if c.claimId == "cl_weak"]
    assert weak, "the verifier's claim should have been recorded"
    assert weak[0].renderAs != "assertion"
    assert weak[0].renderAs == "opinion_report"


# ---- Deep Research is an assist, never a primary source (§4.3, M0-c) --------

def test_deep_research_hit_is_secondary_tier_and_never_sole_primary():
    """A DR citation is pinned at secondary and cannot anchor an assertion alone.

    The connector stamps tierHint="secondary" on every hit, and classify_tier lets
    the hint win — so DR can only ever cast one secondary vote. Coverage needs
    ≥1 primary/secondary and the citation gate needs two INDEPENDENT secondaries,
    so a DR hit can contribute to, but never single-handedly establish, a fact.
    """
    from app.research import rubric
    from app.research.sources.deep_research import parse_citations

    hits = parse_citations({"output": [{"content": [{"annotations": [
        {"type": "url_citation", "url": "https://example.gov/report", "title": "R"}]}]}]})
    assert len(hits) == 1
    hit = hits[0]
    assert hit.deepResearchAssisted is True
    assert hit.tierHint == "secondary"
    assert rubric.classify_tier(hit.sourceType, hit.tierHint) == "secondary"

    # even a .go.jp URL arriving via DR stays secondary — the hint, not the host,
    # decides the tier, so DR cannot smuggle in a primary.
    gov = parse_citations({"output": [{"content": [{"annotations": [
        {"type": "url_citation", "url": "https://www.mofa.go.jp/x.html", "title": "G"}]}]}]})[0]
    assert rubric.classify_tier(gov.sourceType, gov.tierHint) == "secondary"

    # one DR-sourced secondary alone does not pass the citation gate
    class _Ev:
        def __init__(self, url, tier):
            self.url, self.tier = url, tier
            self.reliability = type("R", (), {"score": 100})()
    assert rubric.passes_citation_gate([_Ev(hit.url, "secondary")]) is False
    # ...but two independent secondaries do — DR can be one of them
    assert rubric.passes_citation_gate(
        [_Ev("https://a.example/1", "secondary"), _Ev("https://b.example/2", "secondary")]) is True


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
