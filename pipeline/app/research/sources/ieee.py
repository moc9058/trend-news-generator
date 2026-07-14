"""IEEE Xplore connector (design §4.3) — thin adapter over the existing metadata
search API used by collectors/ieee_xplore.py. Requires the free ieee-api-key;
skips gracefully (empty) when unset, like the collector.
"""

from app.config import get_settings
from app.research.schemas import SourceHit, StrategyQuery
from app.research.sources.base import HttpConnector
from app.utils.logging import get_logger

log = get_logger(__name__)

API_URL = "https://ieeexploreapi.ieee.org/api/v1/search/articles"


def parse_articles(payload: dict) -> list[SourceHit]:
    hits = []
    for a in payload.get("articles", []) or []:
        url = a.get("html_url") or a.get("pdf_url") or ""
        title = (a.get("title") or "").strip()
        if not url or not title:
            continue
        authors = [{"name": au.get("full_name", "")}
                   for au in ((a.get("authors") or {}).get("authors") or [])]
        hits.append(SourceHit(
            title=title,
            url=url,
            identifiers={k: v for k, v in {"doi": a.get("doi")}.items() if v},
            snippet=(a.get("abstract") or "")[:300],
            publishedAt=a.get("publication_date"),
            authors=authors,
            venue=a.get("publication_title") or "IEEE Xplore",
            sourceType="paper",
            tierHint="secondary",
            connector="ieee",
            citationCount=a.get("citing_paper_count"),
        ))
    return hits


class IeeeConnector(HttpConnector):
    name = "ieee"

    def _search(self, q: StrategyQuery) -> list[SourceHit]:
        api_key = get_settings().ieee_api_key
        if not api_key:
            log.warning("ieee connector skipped: ieee-api-key not configured")
            return []
        payload = self._get_json(API_URL, params={
            "apikey": api_key,
            "querytext": q.query,
            "sort_field": "article_influence",
            "sort_order": "desc",
            "max_records": min(max(q.maxResults, 1), 25),
        })
        return parse_articles(payload)
