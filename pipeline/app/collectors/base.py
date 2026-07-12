"""Collector protocol. A collector turns one Source into RawItems; the collect
job owns dedup, image fetching and persistence so collectors stay stateless."""

from datetime import datetime
from typing import Optional, Protocol

from pydantic import BaseModel

from app.models import Source


class RawItem(BaseModel):
    title: str
    url: str
    publishedAt: Optional[datetime] = None
    summary: str = ""
    contentText: str = ""
    imageUrl: str = ""
    groundingCitations: list[str] = []


class Collector(Protocol):
    # focus_keywords steers keyword-aware collectors (gemini_grounded); feed-based
    # collectors (rss, ieee_xplore) accept and ignore it.
    def collect(
        self, source: Source, focus_keywords: list[str] | None = None
    ) -> list[RawItem]: ...
