"""IEEE Xplore Metadata Search API collector.

Free tier: register at https://developer.ieee.org for an API key (~200
calls/day, far above our usage). Sources of type ieee_xplore carry a query
string. Skips gracefully (empty result + warning) when no key is configured.
"""

from datetime import datetime, timezone

import httpx

from app.collectors.base import RawItem
from app.config import get_settings
from app.models import Source
from app.utils.logging import get_logger

log = get_logger(__name__)

API_URL = "https://ieeexploreapi.ieee.org/api/v1/search/articles"
MAX_RECORDS = 10


def parse_articles(payload: dict) -> list[RawItem]:
    items = []
    for article in payload.get("articles", []):
        url = article.get("html_url") or article.get("pdf_url") or ""
        title = (article.get("title") or "").strip()
        if not url or not title:
            continue
        published = None
        date_str = article.get("publication_date") or ""
        for fmt in ("%d %B %Y", "%B %Y", "%Y"):
            try:
                published = datetime.strptime(date_str, fmt).replace(tzinfo=timezone.utc)
                break
            except ValueError:
                continue
        items.append(
            RawItem(
                title=title,
                url=url,
                publishedAt=published,
                summary=(article.get("abstract") or "")[:2000],
            )
        )
    return items


class IeeeXploreCollector:
    def __init__(self, client: httpx.Client | None = None):
        self._client = client or httpx.Client(timeout=20)

    def collect(
        self, source: Source, focus_keywords: list[str] | None = None
    ) -> list[RawItem]:  # focus_keywords ignored: IEEE query is set on the source
        api_key = get_settings().ieee_api_key
        if not api_key:
            log.warning(
                "ieee_xplore source skipped: ieee-api-key not configured",
                extra={"fields": {"source": source.id}},
            )
            return []
        resp = self._client.get(
            API_URL,
            params={
                "apikey": api_key,
                "querytext": source.query,
                "sort_field": "publication_date",
                "sort_order": "desc",
                "max_records": MAX_RECORDS,
            },
        )
        resp.raise_for_status()
        return parse_articles(resp.json())
