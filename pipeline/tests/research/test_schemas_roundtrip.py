"""P1: intermediate schemas round-trip the design's golden JSON (§4.5 / §4.7)."""

from app.research.schemas import (
    LEGACY_PHASE_MAP,
    Claim,
    CoverageReport,
    EvidenceRecord,
    Phase,
    ResearchRequest,
    ResearchRun,
    SourceHit,
)

# --- golden fixtures copied from design §4.7 / §4.5 (abbreviated but faithful) ---

RESEARCH_RUN = {
    "id": "rr_20260801_x7k2m9", "trigger": "manual", "requestedBy": "u@example.com",
    "theme": "天皇の戦争への責任", "questions": [], "depth": "standard",
    "budget": {"usdCap": 10.0, "usdSpent": 0.42, "fetchCap": 80, "fetchUsed": 0, "drCallsUsed": 0},
    "languages": ["ja", "ko", "en"], "canonicalLanguage": "ja",
    "status": "running", "phase": "R2", "loops": 0,
    "claimedBy": "job-generate-report-abc12", "heartbeatAt": "2026-08-01T07:03:11+09:00",
    "plan": {"themeClass": "politics_history", "contested": True, "rqs": [
        {"id": "rq1", "q": "戦前の憲法体制下で天皇の権限は", "strategies": ["gov_docs", "books", "academic"]},
    ]},
    "postId": None, "createdAt": "2026-08-01T07:00:02+09:00",
}

SOURCE_HITS = [
    {"title": "第102回国会 参議院内閣委員会 第3号", "url": "https://kokkai.ndl.go.jp/x",
     "identifiers": {"kokkaiIssueId": "110214889X00319881213"}, "snippet": "…責任という…",
     "publishedAt": "1988-12-13", "sourceType": "parliamentary_record", "tierHint": "primary",
     "connector": "kokkai", "contentText": "(full text)"},
    {"title": "Attention Is All You Need", "url": "https://arxiv.org/abs/1706.03762",
     "identifiers": {"arxivId": "1706.03762", "doi": "10.48550/arXiv.1706.03762"},
     "authors": [{"name": "Vaswani, A."}], "publishedAt": "2017-06-12", "venue": "NeurIPS 2017",
     "sourceType": "paper", "tierHint": "primary", "connector": "academic",
     "rawScore": 0.97, "citationCount": 150000},
]

EVIDENCE = {
    "evidenceId": "3f2a9c", "runId": "rr_20260801_x7k2m9", "rqIds": ["rq1", "rq3"],
    "sourceType": "parliamentary_record", "tier": "primary",
    "title": "第102回国会 参議院 内閣委員会 第3号",
    "authors": [{"name": "答弁者", "role": "speaker"}], "publisher": "国立国会図書館",
    "venue": "国会会議録", "publishedAt": "1988-12-13", "accessedAt": "2026-08-01T09:12:00+09:00",
    "url": "https://kokkai.ndl.go.jp/x", "identifiers": {"kokkaiIssueId": "110214889X00319881213"},
    "language": "ja",
    "archive": {"gcsUri": "gs://b/research/rr/snapshots/3f2a9c.txt", "sha256": "abc",
                "mimeType": "text/plain", "fetchedBy": "kokkai-api"},
    "reliability": {"score": 88, "base": 40, "signals": {"venueAuthority": 15, "corroboration": 9},
                    "penalties": {}, "rationale": "国会公式記録(一次)。"},
    "extraction": {"excerpt": "…本文…", "quotes": [
        {"quoteId": "q1", "text": "「……」", "locator": {"charStart": 1200, "charEnd": 1289}}],
        "claims": ["cl_04", "cl_11"], "stance": "positionA", "isInterpretation": False},
    "retrieval": {"connector": "kokkai", "query": "天皇 戦争責任", "rank": 2, "loop": 0,
                  "deepResearchAssisted": False},
}

CLAIMS = [
    {"claimId": "cl_04", "rqId": "rq2", "text": "1946年の東京裁判で天皇は訴追されなかった",
     "evidenceIds": ["3f2a9c", "8b1d0e"], "verdict": "corroborated",
     "tierMix": {"primary": 1, "secondary": 1}, "contested": False, "confidence": 0.95,
     "renderAs": "assertion"},
    {"claimId": "cl_11", "rqId": "rq3", "text": "退位すべきだったとする立場は戦後直後から存在した",
     "evidenceIds": ["c77a21"], "verdict": "single_source", "stance": "positionB",
     "isInterpretation": True, "renderAs": "inference"},
]

COVERAGE = {
    "loops": 1, "rqCoverage": [
        {"rqId": "rq1", "evidence": 9, "tiers": {"primary": 4, "secondary": 5}, "resolved": True},
        {"rqId": "rq3", "evidence": 3, "tiers": {"secondary": 3}, "resolved": False,
         "gap": "positionA 側の学術資料が不足", "nextQueries": ["…"]}],
    "decision": "loop", "budgetRemaining": 5.1,
}


def _roundtrips(model_cls, data, key_exclude=None):
    """Build from JSON, dump, rebuild — key fields must survive both hops."""
    obj = model_cls(**data)
    dumped = obj.model_dump(mode="json")
    rebuilt = model_cls(**dumped)
    return obj, rebuilt


def test_research_run_roundtrip():
    obj, rebuilt = _roundtrips(ResearchRun, RESEARCH_RUN)
    # the fixture's legacy phase "R2" is bridged to "gather" by the compat shim
    assert obj.status == "running" and obj.phase == "gather"
    assert obj.budget.usdCap == 10.0 and obj.budget.usdSpent == 0.42
    assert obj.plan.themeClass == "politics_history" and obj.plan.contested is True
    assert obj.plan.rqs[0].id == "rq1" and obj.plan.rqs[0].strategies == ["gov_docs", "books", "academic"]
    assert obj.postId is None
    assert rebuilt.plan.rqs[0].q == obj.plan.rqs[0].q  # survives dump→reload


def test_research_run_current_phase_roundtrips_unchanged():
    obj, rebuilt = _roundtrips(ResearchRun, {**RESEARCH_RUN, "phase": "verify"})
    assert obj.phase == "verify" and rebuilt.phase == "verify"


def test_legacy_phase_map_covers_all_old_phases_with_valid_targets():
    assert set(LEGACY_PHASE_MAP) == {"R0", "R1", "R2", "R3", "R4", "R5",
                                     "R6", "R7", "R7L", "R8", "R9"}
    for target in LEGACY_PHASE_MAP.values():
        assert Phase(target)  # every mapped value is a valid current Phase
    for legacy, target in LEGACY_PHASE_MAP.items():
        assert ResearchRun(id="x", phase=legacy).phase == target


def test_source_hit_roundtrip():
    kokkai = SourceHit(**SOURCE_HITS[0])
    paper = SourceHit(**SOURCE_HITS[1])
    assert kokkai.identifiers["kokkaiIssueId"] == "110214889X00319881213"
    assert kokkai.contentText == "(full text)"  # API-returned full text preserved
    assert paper.citationCount == 150000 and paper.rawScore == 0.97
    assert paper.authors[0].name == "Vaswani, A."
    assert SourceHit(**paper.model_dump()).identifiers["arxivId"] == "1706.03762"


def test_evidence_record_roundtrip():
    ev = EvidenceRecord(**EVIDENCE)
    assert ev.tier == "primary" and ev.reliability.score == 88
    assert ev.archive.sha256 == "abc" and ev.archive.mimeType == "text/plain"
    assert ev.extraction.quotes[0].locator == {"charStart": 1200, "charEnd": 1289}
    assert ev.extraction.claims == ["cl_04", "cl_11"]
    # nested structures survive a full dump→reload
    rebuilt = EvidenceRecord(**ev.model_dump(mode="json"))
    assert rebuilt.reliability.signals["venueAuthority"] == 15
    assert rebuilt.retrieval.connector == "kokkai"


def test_claim_roundtrip():
    assertion = Claim(**CLAIMS[0])
    inference = Claim(**CLAIMS[1])
    assert assertion.verdict == "corroborated" and assertion.renderAs == "assertion"
    assert assertion.tierMix == {"primary": 1, "secondary": 1}
    assert inference.isInterpretation is True and inference.stance == "positionB"


def test_coverage_report_roundtrip():
    cov = CoverageReport(**COVERAGE)
    assert cov.decision == "loop" and cov.budgetRemaining == 5.1
    assert cov.rqCoverage[0].resolved is True
    assert cov.rqCoverage[1].resolved is False and cov.rqCoverage[1].gap


def test_research_request_defaults_accept_empty_body():
    # Scheduler posts `{}` — must not raise, must default (design §4.6 contract 1).
    req = ResearchRequest()
    assert req.theme == "" and req.languages == ["ja", "ko", "en"]
    assert req.canonicalLanguage == "ja" and req.trigger == "manual"
    assert req.budgetUsd == 10.0
