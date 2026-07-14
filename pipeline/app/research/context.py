"""Transient per-execution state threaded through the phases by the harness.

Durable state (run doc, evidence, claims, events) lives in Firestore; this holds
the in-flight artifacts (hits before triage, the draft before handoff) for a
single harness execution. On resume, persisted phases (evidence/claims) are
re-read, so losing this in-memory context on crash is safe.
"""

from dataclasses import dataclass, field
from typing import Optional

from app.research.budget import Budget
from app.research.schemas import (
    AuditReport,
    Claim,
    CoverageReport,
    LocalizedReport,
    ReportDraft,
    ResearchRun,
    SourceHit,
)


@dataclass
class RunContext:
    run: ResearchRun
    budget: Budget
    registry: dict = field(default_factory=dict)   # connector name -> connector
    fetcher: object = None
    # gather (retrieval leg → triage leg)
    hit_index: dict[str, SourceHit] = field(default_factory=dict)   # urlHash -> hit
    hit_rqs: dict[str, set] = field(default_factory=dict)           # urlHash -> {rqId}
    # gather → extract
    selected: list[SourceHit] = field(default_factory=list)
    # verify → write (coverage drives the verify→gather loop)
    claims: list[Claim] = field(default_factory=list)
    coverage: Optional[CoverageReport] = None
    # write → review
    draft: Optional[ReportDraft] = None
    localized: dict[str, LocalizedReport] = field(default_factory=dict)
    audit: Optional[AuditReport] = None
    review_decision: str = ""  # "revise" | "proceed", set by review.run
    revisions: int = 0
    postId: str = ""

    @property
    def hits(self) -> list[SourceHit]:
        return list(self.hit_index.values())
