"""Intermediate schemas for the Research Agent (report format).

Every phase (R0–R9) consumes and produces one of these pydantic-validated
objects; a phase's LLM never sees the previous phase's raw text — only the
validated JSON — which is what breaks the hallucination chain (design §3.2).

Contract flow (design §4.8):
  ResearchRequest → ResearchPlan → StrategyQuery → SourceHit → EvidenceRecord
  → Claim → CoverageReport → ReportDraft(canonical) → LocalizedReport ×3 → AuditReport

The JSON shapes here are kept identical to the golden examples in design §4.5 / §4.7
so those fixtures round-trip unchanged.
"""

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


# --------------------------------------------------------------------------- #
# Enums (research-internal; researchRunStatuses is also mirrored in            #
# shared/constants.json for the admin UI).                                     #
# --------------------------------------------------------------------------- #

class ResearchRunStatus(str, Enum):
    queued = "queued"
    running = "running"
    awaiting_plan_approval = "awaiting_plan_approval"
    awaiting_review = "awaiting_review"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"
    budget_exhausted = "budget_exhausted"


# Terminal states: a run here is never claimed/resumed.
TERMINAL_STATUSES = {
    ResearchRunStatus.awaiting_review,
    ResearchRunStatus.completed,
    ResearchRunStatus.failed,
    ResearchRunStatus.cancelled,
    ResearchRunStatus.budget_exhausted,
}


class Phase(str, Enum):
    R0 = "R0"    # intake
    R1 = "R1"    # plan
    R2 = "R2"    # retrieve
    R3 = "R3"    # triage
    R4 = "R4"    # extract
    R5 = "R5"    # verify
    R6 = "R6"    # gap
    R7 = "R7"    # write (canonical)
    R7L = "R7L"  # localize
    R8 = "R8"    # critic
    R9 = "R9"    # handoff


class Tier(str, Enum):
    primary = "primary"
    secondary = "secondary"
    tertiary = "tertiary"


class EvidenceSourceType(str, Enum):
    official_document = "official_document"
    parliamentary_record = "parliamentary_record"
    paper = "paper"
    book = "book"
    preprint = "preprint"
    quality_news = "quality_news"
    web = "web"


class ThemeClass(str, Enum):
    politics_history = "politics_history"
    science_tech = "science_tech"
    economics = "economics"
    intl_affairs = "intl_affairs"
    society_culture = "society_culture"
    law_regulation = "law_regulation"


class Verdict(str, Enum):
    corroborated = "corroborated"
    single_source = "single_source"
    contested = "contested"
    refuted = "refuted"
    unverified = "unverified"


class RenderAs(str, Enum):
    assertion = "assertion"
    inference = "inference"
    opinion_report = "opinion_report"


# --------------------------------------------------------------------------- #
# Request / plan                                                               #
# --------------------------------------------------------------------------- #

class ResearchRequest(BaseModel):
    # All fields default so Cloud Scheduler's empty `{}` body does not 422 (§4.6).
    theme: str = ""
    questions: list[str] = []
    categoryId: str = ""
    depth: str = "standard"  # standard | light
    budgetUsd: float = 10.0  # ≤ 30
    languages: list[str] = ["ja", "ko", "en"]
    canonicalLanguage: str = "ja"
    planApproval: bool = False
    requestedBy: str = ""
    trigger: str = "manual"  # manual | scheduled


class ResearchQuestion(BaseModel):
    id: str  # rq1, rq2, …
    q: str
    strategies: list[str] = []  # connector names, priority order
    resolved: bool = False


class ResearchPlan(BaseModel):
    themeClass: str  # ThemeClass value (kept as str for LLM-tolerant parsing)
    contested: bool = False
    rqs: list[ResearchQuestion] = []


# --------------------------------------------------------------------------- #
# Retrieval                                                                    #
# --------------------------------------------------------------------------- #

class StrategyQuery(BaseModel):
    rqId: str
    query: str
    language: str = "ja"
    dateRange: Optional[str] = None
    siteFilters: list[str] = []
    maxResults: int = 10
    connector: str = ""


class Author(BaseModel):
    name: str
    affiliation: str = ""
    role: str = ""


class SourceHit(BaseModel):
    title: str
    url: str
    identifiers: dict = {}  # {doi, arxivId, isbn, kokkaiIssueId, …}
    snippet: str = ""
    publishedAt: Optional[str] = None  # partial dates allowed ("1946", "1988-12-13")
    authors: list[Author] = []
    venue: str = ""
    sourceType: str = ""
    tierHint: str = ""
    connector: str = ""
    rawScore: Optional[float] = None
    citationCount: Optional[int] = None
    contentText: str = ""  # kokkai etc. return full text → skip R4 fetch
    deepResearchAssisted: bool = False


# --------------------------------------------------------------------------- #
# Evidence (design §4.5 — every fetched source is stored in this shape)        #
# --------------------------------------------------------------------------- #

class Quote(BaseModel):
    quoteId: str
    text: str
    locator: dict = {}  # {charStart, charEnd} — machine-verifiable offsets


class Archive(BaseModel):
    gcsUri: str = ""
    sha256: str = ""
    mimeType: str = ""
    fetchedBy: str = ""


class Reliability(BaseModel):
    score: int = 0
    base: int = 0
    signals: dict = {}
    penalties: dict = {}
    rationale: str = ""


class Extraction(BaseModel):
    excerpt: str = ""
    quotes: list[Quote] = []
    claims: list[str] = []
    stance: str = ""
    isInterpretation: bool = False


class Retrieval(BaseModel):
    connector: str = ""
    query: str = ""
    rank: int = 0
    loop: int = 0
    deepResearchAssisted: bool = False


class EvidenceRecord(BaseModel):
    evidenceId: str = ""  # sha256(canonicalUrl)[:32]
    runId: str = ""
    rqIds: list[str] = []
    sourceType: str = ""
    tier: str = ""
    title: str = ""
    authors: list[Author] = []
    publisher: str = ""
    venue: str = ""
    publishedAt: Optional[str] = None
    accessedAt: Optional[str] = None
    url: str = ""
    identifiers: dict = {}
    language: str = ""
    archive: Archive = Field(default_factory=Archive)
    reliability: Reliability = Field(default_factory=Reliability)
    extraction: Extraction = Field(default_factory=Extraction)
    retrieval: Retrieval = Field(default_factory=Retrieval)


# --------------------------------------------------------------------------- #
# Verification / coverage                                                      #
# --------------------------------------------------------------------------- #

class Claim(BaseModel):
    claimId: str
    rqId: str = ""
    text: str = ""
    evidenceIds: list[str] = []
    verdict: str = ""  # Verdict value
    tierMix: dict = {}  # {"primary": n, "secondary": n}
    stance: str = ""
    contested: bool = False
    isInterpretation: bool = False
    confidence: float = 0.0
    renderAs: str = ""  # RenderAs value
    usedInSections: list[str] = []


class RqCoverage(BaseModel):
    rqId: str
    evidence: int = 0
    tiers: dict = {}
    resolved: bool = False
    gap: str = ""
    nextQueries: list[str] = []


class CoverageReport(BaseModel):
    loops: int = 0
    rqCoverage: list[RqCoverage] = []
    decision: str = ""  # "loop" | "finalize"
    budgetRemaining: float = 0.0


# --------------------------------------------------------------------------- #
# Report drafts                                                                #
# --------------------------------------------------------------------------- #

class ReportSection(BaseModel):
    heading: str
    claimIds: list[str] = []
    body: str = ""  # markdown
    footnotes: list[int] = []


class ReportDraft(BaseModel):
    """canonical (ja) draft — the frozen structured skeleton the localizers copy."""
    language: str = "ja"
    title: str = ""
    summary: str = ""
    sections: list[ReportSection] = []
    references: list[str] = []  # evidenceIds in footnote order


class LocalizedReport(BaseModel):
    language: str
    title: str = ""
    summary: str = ""
    body: str = ""  # rendered markdown
    footnoteCount: int = 0
    notionPageId: str = ""
    notionUrl: str = ""


class AuditFinding(BaseModel):
    kind: str  # hallucinated_citation | unsupported_assertion | number_mismatch | …
    location: str = ""
    detail: str = ""
    action: str = ""  # deleted | demoted | fixed


class AuditReport(BaseModel):
    citeCheckPassRate: float = 0.0
    triLanguageConsistent: bool = True
    findings: list[AuditFinding] = []
    passed: bool = False


# --------------------------------------------------------------------------- #
# Run state (top-level researchRuns/{runId} document — design §4.7)            #
# --------------------------------------------------------------------------- #

class BudgetState(BaseModel):
    usdCap: float = 10.0
    usdSpent: float = 0.0
    fetchCap: int = 80
    fetchUsed: int = 0
    drCallsUsed: int = 0


class ResearchRun(BaseModel):
    id: str = ""  # rr_{YYYYMMDD}_{rand6}
    trigger: str = "manual"
    requestedBy: str = ""
    categoryId: str = ""
    theme: str = ""
    questions: list[str] = []
    depth: str = "standard"
    budget: BudgetState = Field(default_factory=BudgetState)
    languages: list[str] = ["ja", "ko", "en"]
    canonicalLanguage: str = "ja"
    status: str = ResearchRunStatus.queued.value
    phase: str = Phase.R0.value
    loops: int = 0
    planApproval: bool = False
    claimedBy: str = ""
    claimedAt: Optional[datetime] = None
    heartbeatAt: Optional[datetime] = None
    cancelRequested: bool = False
    plan: Optional[ResearchPlan] = None
    postId: Optional[str] = None
    error: str = ""
    createdAt: Optional[datetime] = None
    updatedAt: Optional[datetime] = None


class AuditEvent(BaseModel):
    """Append-only audit-log entry (researchRuns/{id}/events) — design §6.5."""
    ts: Optional[datetime] = None
    phase: str = ""
    actor: str = ""
    action: str = ""  # llm_call|fetch|connector_search|phase_start|phase_end|budget_check|fallback|circuit_break
    target: str = ""
    model: str = ""
    tokensIn: int = 0
    tokensOut: int = 0
    costUsd: float = 0.0
    ok: bool = True
    error: Optional[str] = None
    durationMs: int = 0
    detail: dict = {}
