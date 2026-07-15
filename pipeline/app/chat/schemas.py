"""Chat data model: Firestore documents + the graph's LLM output schemas.

Two families live here. `ChatThread`/`ChatMessage` are persisted (see
`app/repo/chat.py`); `ChatResearchPlan`/`ChatSelection`/`ChatGapReport` are
transient LLM outputs validated by `llm.structured`. `ChatReading` is transient
too — fetched body text is never persisted (design doc 11 §5.5).
"""

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field

from app.models import ChatSeed, ChatSeedSource  # noqa: F401 — re-exported below


class ChatMode(str, Enum):
    chat = "chat"          # sparring partner, no tools
    research = "research"  # autonomous source-backed investigation


class ChatDepth(str, Enum):
    quick = "quick"
    deep = "deep"


class ChatMessageStatus(str, Enum):
    streaming = "streaming"
    complete = "complete"
    error = "error"
    cancelled = "cancelled"


class ChatThreadStatus(str, Enum):
    active = "active"
    archived = "archived"


# --------------------------------------------------------------------------- #
# Persisted documents                                                          #
# --------------------------------------------------------------------------- #

class ChatSource(BaseModel):
    """One numbered citation shown under an assistant answer."""
    n: int
    url: str
    title: str = ""
    tier: str = ""       # primary | secondary | tertiary
    score: int = 0       # rubric.score_reliability
    connector: str = ""


class ChatUsage(BaseModel):
    costUsd: float = 0.0
    promptTokens: int = 0
    completionTokens: int = 0
    model: str = ""


class ChatHandoff(BaseModel):
    format: str          # short | article | report
    refId: str           # postId or researchRun id
    at: Optional[datetime] = None


class ChatThreadTotals(BaseModel):
    messages: int = 0
    costUsd: float = 0.0


class ChatThread(BaseModel):
    id: str = ""  # ct_{YYYYMMDD}_{rand6}
    title: str = ""
    requestedBy: str = ""
    status: str = ChatThreadStatus.active.value
    cancelRequested: bool = False
    totals: ChatThreadTotals = Field(default_factory=ChatThreadTotals)
    createdAt: Optional[datetime] = None
    updatedAt: Optional[datetime] = None
    lastMessageAt: Optional[datetime] = None


class ChatMessage(BaseModel):
    id: str = ""
    seq: int = 0         # display order; assigned from thread.totals.messages
    role: str = "user"   # user | assistant
    mode: str = ChatMode.chat.value
    depth: Optional[str] = None
    content: str = ""
    status: str = ChatMessageStatus.complete.value
    sources: list[ChatSource] = []
    usage: Optional[ChatUsage] = None
    handoffs: list[ChatHandoff] = []
    error: str = ""
    createdAt: Optional[datetime] = None


# ChatSeed/ChatSeedSource (the chat → generator handoff payload) live in
# app/models.py so `generators/` can consume them without importing `chat/`.
# Re-exported here because they are part of chat's vocabulary.
__all__ = ["ChatSeed", "ChatSeedSource"]


# --------------------------------------------------------------------------- #
# Transient graph artifacts                                                    #
# --------------------------------------------------------------------------- #

class ChatQuery(BaseModel):
    query: str
    connector: str = ""
    language: str = "ja"


class ChatResearchPlan(BaseModel):
    """plan_queries output: what to search and where."""
    themeClass: str = "society_culture"   # keys of phases/plan.py STRATEGY_MATRIX
    queries: list[ChatQuery] = []
    rationale: str = ""


class ChatSelectionItem(BaseModel):
    index: int
    keep: bool = True
    relevance: float = 0.0


class ChatSelection(BaseModel):
    """select output (deep only): which hits are worth fetching."""
    selections: list[ChatSelectionItem] = []


class ChatGapReport(BaseModel):
    """gap_check output (deep only): is what we read enough to answer?"""
    decision: str = "finalize"   # loop | finalize
    missing: list[str] = []
    followupQueries: list[ChatQuery] = []


class ChatTitle(BaseModel):
    title: str = ""


class ChatHandoffTheme(BaseModel):
    """HANDOFF_THEME output: a report theme distilled from the conversation."""
    theme: str = ""
    questions: list[str] = []


class ChatReading(BaseModel):
    """One source whose body we actually read. Never persisted — the extracted
    text is the graph's working material and can be large."""
    n: int = 0
    url: str
    title: str = ""
    tier: str = ""
    score: int = 0
    connector: str = ""
    text: str = ""
    urlHash: str = ""

    def to_source(self) -> ChatSource:
        return ChatSource(n=self.n, url=self.url, title=self.title, tier=self.tier,
                          score=self.score, connector=self.connector)
