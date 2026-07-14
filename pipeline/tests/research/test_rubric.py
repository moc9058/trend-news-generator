"""P3: reliability rubric, tier classification, citation gate, render mode (§4.2)."""

from app.research.rubric import (
    classify_tier,
    passes_citation_gate,
    render_as,
    score_reliability,
    venue_authority,
)
from app.research.schemas import EvidenceRecord, Reliability


def test_venue_authority_tiers():
    assert venue_authority("https://kokkai.ndl.go.jp/x") == 15
    assert venue_authority("https://laws.e-gov.go.jp/x") == 15
    assert venue_authority("https://arxiv.org/abs/1") == 12
    assert venue_authority("https://www.reuters.com/x") == 8
    assert venue_authority("https://randomblog.example/x") == 0


def test_score_reliability_adds_signals_and_caps():
    r = score_reliability("parliamentary_record", "https://kokkai.ndl.go.jp/x",
                          corroboration=9, recency_fit=4)
    assert r.base == 40 and r.signals["venueAuthority"] == 15
    assert r.score == 40 + 15 + 4 + 9  # 68
    capped = score_reliability("web", "https://blog.example/x",
                               corroboration=20, penalties={"contentFarm": 20})
    assert capped.signals["corroboration"] == 15  # capped at 15
    assert capped.score == max(0, 15 + 0 + 0 + 15 - 20)  # 10


def test_classify_tier_hint_wins():
    assert classify_tier("parliamentary_record") == "primary"
    assert classify_tier("paper") == "secondary"
    assert classify_tier("web") == "tertiary"
    assert classify_tier("paper", "primary") == "primary"


def _ev(tier, score, url):
    return EvidenceRecord(evidenceId="e", tier=tier, url=url,
                          reliability=Reliability(score=score))


def test_citation_gate():
    assert passes_citation_gate([_ev("primary", 70, "https://a.go.jp/1")]) is True
    assert passes_citation_gate([_ev("primary", 50, "https://a.go.jp/1")]) is False  # weak
    assert passes_citation_gate([_ev("secondary", 40, "https://a.com/1"),
                                 _ev("secondary", 40, "https://b.com/1")]) is True
    assert passes_citation_gate([_ev("secondary", 40, "https://a.com/1"),
                                 _ev("secondary", 40, "https://a.com/2")]) is False  # same domain


def test_render_as():
    assert render_as("corroborated", False, True) == "assertion"
    assert render_as("corroborated", True, True) == "inference"      # interpretation
    assert render_as("single_source", False, False) == "inference"
    assert render_as("refuted", False, False) == "opinion_report"
