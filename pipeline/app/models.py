"""Pydantic models mirroring the Firestore schema (see README / plan)."""

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, model_validator


class Format(str, Enum):
    """Deliverable kind. Replaces the old delivery-cadence enum (daily/weekly/
    monthly) — see docs/tech-report/05-detailed-design/10-research-agent.md §1."""

    short = "short"      # was daily  — recent-items digest, auto-published
    article = "article"  # was weekly — trend analysis, draft → approval
    report = "report"    # was monthly — deep-dive research report (Research Agent)


# Legacy delivery-cadence → format, used by the Post compat shim below and by
# scripts/migrate_cadence_to_format.py. Kept here as the single source of truth.
LEGACY_CADENCE_TO_FORMAT = {"daily": "short", "weekly": "article", "monthly": "report"}


class Channel(str, Enum):
    x = "x"
    threads = "threads"
    notion = "notion"


class PostStatus(str, Enum):
    draft = "draft"
    approved = "approved"
    publishing = "publishing"
    published = "published"
    partially_published = "partially_published"
    failed = "failed"


class ChannelStatus(str, Enum):
    pending = "pending"
    published = "published"
    failed = "failed"
    skipped = "skipped"


class SourceType(str, Enum):
    rss = "rss"  # also handles Atom, including the arXiv API (export.arxiv.org)
    gemini_grounded = "gemini_grounded"
    ieee_xplore = "ieee_xplore"


class Category(BaseModel):
    slug: str
    name: str
    searchHints: list[str] = []
    enabled: bool = True
    sortOrder: int = 0


class Source(BaseModel):
    id: str = ""
    categoryId: str
    type: SourceType
    url: str = ""  # rss
    query: str = ""  # gemini_grounded
    enabled: bool = True
    etag: str = ""
    lastModified: str = ""
    lastFetchedAt: Optional[datetime] = None


class PromptTemplate(BaseModel):
    id: str = ""  # {categoryId}_{format}
    categoryId: str
    format: Format
    systemPrompt: str
    userPromptTemplate: str  # placeholders: {items} {category} {date} {language} {keywords}
    # article/report two-stage generation: stage-1 selection/outline prompts
    outlineSystemPrompt: str = ""
    outlineUserPromptTemplate: str = ""
    modelOverride: str = ""
    # focus keywords for this category x format: steer collection (union per
    # category) and give extra weight during generation. Empty = no steering.
    focusKeywords: list[str] = []
    enabled: bool = True


class ImageRef(BaseModel):
    gcsPath: str
    mime: str


class Item(BaseModel):
    id: str = ""  # sha256(canonicalUrl)[:32]
    categoryId: str
    title: str
    canonicalUrl: str
    publishedAt: Optional[datetime] = None
    collectedAt: Optional[datetime] = None
    summary: str = ""
    contentText: str = ""  # capped at 10k chars
    titleNormHash: str = ""
    sourceId: str = ""
    imageRefs: list[ImageRef] = []
    groundingCitations: list[str] = []
    usedInPostIds: list[str] = []


class ChannelState(BaseModel):
    enabled: bool = True
    lang: str = "en"
    text: str = ""
    threadParts: list[str] = []
    status: ChannelStatus = ChannelStatus.pending
    externalId: str = ""
    url: str = ""
    error: str = ""
    # threads only
    imageGcsPath: str = ""
    containerId: str = ""
    # notion only
    pageId: str = ""


class TokenUsage(BaseModel):
    inputTokens: int = 0
    outputTokens: int = 0
    costUsd: float = 0.0


class Post(BaseModel):
    id: str = ""
    format: Format
    categoryId: str
    status: PostStatus = PostStatus.draft
    title: str = ""
    summary: str = ""
    body: str = ""  # markdown
    sourceItemIds: list[str] = []
    tokenUsage: TokenUsage = Field(default_factory=TokenUsage)
    channels: dict[str, ChannelState] = {}
    createdAt: Optional[datetime] = None
    approvedBy: str = ""
    publishedAt: Optional[datetime] = None

    @model_validator(mode="before")
    @classmethod
    def _accept_legacy_cadence(cls, data):
        """Bridge pre-migration docs that still carry `cadence` instead of
        `format`. posts.old_drafts()/get() build Post(**doc) over EVERY draft, so
        a single un-migrated doc would otherwise crash the cleanup_drafts job and
        the publish API. The migration removes the legacy field; this shim only
        covers the deploy→migrate window and makes rollbacks safe."""
        if isinstance(data, dict) and "format" not in data and "cadence" in data:
            legacy = data["cadence"]
            legacy = getattr(legacy, "value", legacy)
            data = {**data, "format": LEGACY_CADENCE_TO_FORMAT.get(legacy, legacy)}
        return data


class ChannelConfig(BaseModel):
    id: str = ""  # {categoryId}_{format}_{channel}
    categoryId: str
    format: Format
    channel: Channel
    enabled: bool = True
    language: str = "en"


class RunStats(BaseModel):
    collected: int = 0
    deduped: int = 0
    postsCreated: int = 0
    published: int = 0
    failed: int = 0
    deleted: int = 0


class Run(BaseModel):
    id: str = ""
    jobType: str
    startedAt: Optional[datetime] = None
    finishedAt: Optional[datetime] = None
    ok: bool = True
    stats: RunStats = Field(default_factory=RunStats)
    errors: list[str] = []
    costUsd: float = 0.0


class AppSettings(BaseModel):
    timezone: str = "Asia/Tokyo"
    shortRequireApproval: bool = False
    xAllowUrlOnShort: bool = False
    attachImages: bool = True
