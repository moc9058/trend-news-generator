"""Reliability scoring, tier classification and the citation gate (design §4.2).

All PURE functions — the numeric trust model lives here so it is reproducible and
unit-tested, separate from the LLM's judgement of what a source *says*.
"""

from urllib.parse import urlsplit

from app.research.schemas import Reliability

# base score by source type (§4.2 rubric)
BASE_SCORE = {
    "official_document": 40, "parliamentary_record": 40,
    "paper": 38, "book": 32, "preprint": 30, "quality_news": 25, "web": 15,
}

# tier inferred from source type when the connector gave no hint
TYPE_TIER = {
    "parliamentary_record": "primary", "official_document": "primary", "preprint": "primary",
    "paper": "secondary", "book": "secondary", "quality_news": "secondary", "web": "tertiary",
}

CITATION_MIN_SCORE = 60  # a primary must reach this to anchor an assertion alone

_MAJOR_ACADEMIC = ("arxiv.org", "doi.org", "nature.com", "science.org", "springer.com", "ieee.org")
_MAJOR_NEWS = ("reuters.com", "nytimes.com", "ft.com", "bbc.", "nikkei.com", "asahi.com",
               "apnews.com", "economist.com")


def _host(url: str) -> str:
    return (urlsplit(url).hostname or "").lower()


def venue_authority(url: str) -> int:
    """0–15: official gov/NDL highest, then major academic, then major news."""
    host = _host(url)
    if host.endswith(".go.jp") or host.endswith("ndl.go.jp") or "e-gov.go.jp" in host:
        return 15
    if host.endswith(".ac.jp") or host.endswith(".edu") or any(d in host for d in _MAJOR_ACADEMIC):
        return 12
    if any(n in host for n in _MAJOR_NEWS):
        return 8
    return 0


def classify_tier(source_type: str, tier_hint: str = "") -> str:
    if tier_hint in ("primary", "secondary", "tertiary"):
        return tier_hint
    return TYPE_TIER.get(source_type, "tertiary")


def score_reliability(source_type: str, url: str, corroboration: int = 0,
                      recency_fit: int = 0, author_credibility: int = 0,
                      penalties: dict | None = None) -> Reliability:
    penalties = penalties or {}
    base = BASE_SCORE.get(source_type, 15)
    va = venue_authority(url)
    corr = min(max(corroboration, 0), 15)
    rec = min(max(recency_fit, 0), 10)
    ac = min(max(author_credibility, 0), 10)
    pen_total = sum(penalties.values())
    score = max(0, min(100, base + va + ac + rec + corr - pen_total))
    return Reliability(
        score=score, base=base,
        signals={"venueAuthority": va, "authorCredibility": ac,
                 "recencyFit": rec, "corroboration": corr},
        penalties=penalties,
        rationale=f"{source_type} base {base}; venue +{va}; corroboration +{corr}"
                  + (f"; penalties -{pen_total}" if pen_total else ""),
    )


def passes_citation_gate(evidence_list: list) -> bool:
    """An assertion is allowed iff one primary with score≥60 backs it, or two
    INDEPENDENT secondaries (different domains) do (§4.2 citation gate)."""
    primary = [e for e in evidence_list
               if e.tier == "primary" and e.reliability.score >= CITATION_MIN_SCORE]
    if primary:
        return True
    secondary_domains = {_host(e.url) for e in evidence_list if e.tier == "secondary"}
    return len(secondary_domains) >= 2


def render_as(verdict: str, is_interpretation: bool, gate_ok: bool) -> str:
    """How a claim is rendered in the report (§4.8): a gated, corroborated fact is
    an assertion; interpretation/single-source is an inference; the rest is
    reported as opinion."""
    if is_interpretation:
        return "inference"
    if gate_ok and verdict == "corroborated":
        return "assertion"
    if verdict in ("single_source", "contested"):
        return "inference"
    return "opinion_report"
