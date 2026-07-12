"""RSS/Atom collector with conditional GET (ETag / Last-Modified)."""

import time
from datetime import datetime, timezone

import feedparser
import httpx

from app.collectors.base import RawItem
from app.models import Source
from app.repo import configs
from app.utils.logging import get_logger

log = get_logger(__name__)

MAX_ENTRIES_PER_FEED = 30


def _entry_published(entry) -> datetime | None:
    parsed = entry.get("published_parsed") or entry.get("updated_parsed")
    if not parsed:
        return None
    return datetime.fromtimestamp(time.mktime(parsed), tz=timezone.utc)


def _entry_image(entry) -> str:
    for media in entry.get("media_content", []) or []:
        if media.get("url"):
            return media["url"]
    for media in entry.get("media_thumbnail", []) or []:
        if media.get("url"):
            return media["url"]
    for enc in entry.get("enclosures", []) or []:
        if enc.get("type", "").startswith("image/") and enc.get("href"):
            return enc["href"]
    return ""


def parse_feed(content: bytes) -> list[RawItem]:
    feed = feedparser.parse(content)
    items = []
    for entry in feed.entries[:MAX_ENTRIES_PER_FEED]:
        url = entry.get("link", "")
        title = entry.get("title", "").strip()
        if not url or not title:
            continue
        items.append(
            RawItem(
                title=title,
                url=url,
                publishedAt=_entry_published(entry),
                summary=entry.get("summary", "")[:2000],
                imageUrl=_entry_image(entry),
            )
        )
    return items


class RssCollector:
    def __init__(self, client: httpx.Client | None = None):
        self._client = client or httpx.Client(
            timeout=20, follow_redirects=True,
            headers={"User-Agent": "trend-news-generator/1.0"},
        )

    def collect(
        self, source: Source, focus_keywords: list[str] | None = None
    ) -> list[RawItem]:  # focus_keywords ignored: RSS feeds are fixed URLs
        headers = {}
        if source.etag:
            headers["If-None-Match"] = source.etag
        if source.lastModified:
            headers["If-Modified-Since"] = source.lastModified

        resp = self._client.get(source.url, headers=headers)
        if resp.status_code == 304:
            log.info("rss not modified", extra={"fields": {"source": source.url}})
            return []
        resp.raise_for_status()

        if source.id:
            configs.update_source_cache(
                source.id,
                resp.headers.get("etag", ""),
                resp.headers.get("last-modified", ""),
            )
        return parse_feed(resp.content)
