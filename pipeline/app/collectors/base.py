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
    def collect(self, source: Source) -> list[RawItem]: ...
