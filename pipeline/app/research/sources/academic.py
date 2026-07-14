"""Academic connector: Semantic Scholar → OpenAlex → Crossref fallback chain,
plus arXiv direct (additive) — design §4.3, §7.1.

The three general databases are tried in order; the first that returns hits wins
(they overlap heavily, so merging all three wastes budget). arXiv is queried
separately because it surfaces preprints the others index late. Citation counts
are captured so R3 can detect seminal papers by被引用数 (design §4.2 example 2).
"""

import feedparser

from app.config import get_settings
from app.research.schemas import SourceHit, StrategyQuery
from app.research.sources.base import HttpConnector
from app.utils.logging import get_logger

log = get_logger(__name__)

SS_URL = "https://api.semanticscholar.org/graph/v1/paper/search"
OPENALEX_URL = "https://api.openalex.org/works"
CROSSREF_URL = "https://api.crossref.org/works"
ARXIV_URL = "http://export.arxiv.org/api/query"


# --- parsers (pure; unit-tested with respx-mocked payloads) ------------------

def parse_semantic_scholar(payload: dict) -> list[SourceHit]:
    hits = []
    for p in payload.get("data", []) or []:
        ext = p.get("externalIds") or {}
        arxiv = ext.get("ArXiv")
        hits.append(SourceHit(
            title=(p.get("title") or "").strip(),
            url=p.get("url") or (f"https://arxiv.org/abs/{arxiv}" if arxiv else "")
                or (f"https://doi.org/{ext.get('DOI')}" if ext.get("DOI") else ""),
            identifiers={k: v for k, v in {"doi": ext.get("DOI"), "arxivId": arxiv}.items() if v},
            snippet=(p.get("abstract") or "")[:300],
            publishedAt=str(p["year"]) if p.get("year") else None,
            authors=[{"name": a.get("name", "")} for a in (p.get("authors") or [])],
            venue=p.get("venue") or "",
            sourceType="preprint" if arxiv and not ext.get("DOI") else "paper",
            tierHint="secondary",
            connector="academic",
            citationCount=p.get("citationCount"),
        ))
    return [h for h in hits if h.title and h.url]


def parse_openalex(payload: dict) -> list[SourceHit]:
    hits = []
    for w in payload.get("results", []) or []:
        loc = (w.get("primary_location") or {}) or {}
        src = (loc.get("source") or {}) or {}
        doi = (w.get("doi") or "").replace("https://doi.org/", "") or None
        hits.append(SourceHit(
            title=(w.get("title") or "").strip(),
            url=loc.get("landing_page_url") or w.get("doi") or w.get("id") or "",
            identifiers={"doi": doi} if doi else {},
            snippet="",
            publishedAt=str(w["publication_year"]) if w.get("publication_year") else None,
            authors=[{"name": (a.get("author") or {}).get("display_name", "")}
                     for a in (w.get("authorships") or [])],
            venue=src.get("display_name") or "",
            sourceType="paper",
            tierHint="secondary",
            connector="academic",
            citationCount=w.get("cited_by_count"),
        ))
    return [h for h in hits if h.title and h.url]


def parse_crossref(payload: dict) -> list[SourceHit]:
    hits = []
    for it in (payload.get("message") or {}).get("items", []) or []:
        title = (it.get("title") or [""])[0].strip()
        parts = ((it.get("published") or {}).get("date-parts") or [[None]])[0]
        year = parts[0] if parts else None
        hits.append(SourceHit(
            title=title,
            url=it.get("URL") or (f"https://doi.org/{it.get('DOI')}" if it.get("DOI") else ""),
            identifiers={"doi": it.get("DOI")} if it.get("DOI") else {},
            snippet=(it.get("abstract") or "")[:300],
            publishedAt=str(year) if year else None,
            authors=[{"name": " ".join(x for x in [a.get("given"), a.get("family")] if x)}
                     for a in (it.get("author") or [])],
            venue=(it.get("container-title") or [""])[0],
            sourceType="paper",
            tierHint="secondary",
            connector="academic",
            citationCount=it.get("is-referenced-by-count"),
        ))
    return [h for h in hits if h.title and h.url]


def parse_arxiv(atom_text: str) -> list[SourceHit]:
    feed = feedparser.parse(atom_text)
    hits = []
    for e in feed.entries:
        arxiv_id = (e.get("id") or "").rsplit("/abs/", 1)[-1]
        hits.append(SourceHit(
            title=(e.get("title") or "").strip().replace("\n", " "),
            url=e.get("id") or "",
            identifiers={k: v for k, v in {
                "arxivId": arxiv_id or None,
                "doi": e.get("arxiv_doi"),
            }.items() if v},
            snippet=(e.get("summary") or "")[:300].replace("\n", " "),
            publishedAt=(e.get("published") or "")[:10] or None,
            authors=[{"name": a.get("name", "")} for a in (e.get("authors") or [])],
            venue="arXiv",
            sourceType="preprint",
            tierHint="primary",  # original preprint = primary for a science_tech RQ
            connector="academic",
        ))
    return [h for h in hits if h.title and h.url]


class AcademicConnector(HttpConnector):
    name = "academic"

    def _search(self, q: StrategyQuery) -> list[SourceHit]:
        n = min(max(q.maxResults, 1), 20)
        hits = self._general_chain(q.query, n)
        hits += self._arxiv(q.query, n)
        return hits

    def _general_chain(self, query: str, n: int) -> list[SourceHit]:
        """SS → OpenAlex → Crossref: first non-empty wins."""
        for name, fn in (("semantic_scholar", self._semantic_scholar),
                         ("openalex", self._openalex),
                         ("crossref", self._crossref)):
            try:
                hits = fn(query, n)
                if hits:
                    return hits
            except Exception as exc:  # noqa: BLE001 — fall through to next source
                log.warning("academic source failed, falling back", extra={"fields": {
                    "source": name, "error": str(exc)}})
        return []

    def _semantic_scholar(self, query: str, n: int) -> list[SourceHit]:
        headers = {}
        key = get_settings().semantic_scholar_api_key
        if key:
            headers["x-api-key"] = key
        payload = self._get_json(SS_URL, params={
            "query": query, "limit": n,
            "fields": "title,abstract,url,year,authors,externalIds,citationCount,venue",
        }, headers=headers)
        return parse_semantic_scholar(payload)

    def _openalex(self, query: str, n: int) -> list[SourceHit]:
        return parse_openalex(self._get_json(OPENALEX_URL, params={
            "search": query, "per-page": n}))

    def _crossref(self, query: str, n: int) -> list[SourceHit]:
        return parse_crossref(self._get_json(CROSSREF_URL, params={
            "query": query, "rows": n}))

    def _arxiv(self, query: str, n: int) -> list[SourceHit]:
        try:
            resp = self._get(ARXIV_URL, params={
                "search_query": f"all:{query}", "max_results": n,
                "sortBy": "relevance", "sortOrder": "descending"})
            return parse_arxiv(resp.text)
        except Exception as exc:  # noqa: BLE001 — arXiv is additive, non-fatal
            log.warning("arxiv failed", extra={"fields": {"error": str(exc)}})
            return []
