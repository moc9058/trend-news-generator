"""Books connector: Google Books API (primary) + NDL Search SRU (additive) —
design §4.3. Books are secondary sources (analysis); academic monographs on a
politics_history theme carry weight (§4.2 matrix).
Google Books: no key needed for basic search. NDL SRU: free, XML.
"""

from xml.etree import ElementTree as ET

from app.research.schemas import SourceHit, StrategyQuery
from app.research.sources.base import HttpConnector
from app.utils.logging import get_logger

log = get_logger(__name__)

GOOGLE_BOOKS_URL = "https://www.googleapis.com/books/v1/volumes"
NDL_SRU_URL = "https://ndlsearch.ndl.go.jp/api/sru"

_DC = "{http://purl.org/dc/elements/1.1/}"


def parse_google_books(payload: dict) -> list[SourceHit]:
    hits = []
    for v in payload.get("items", []) or []:
        info = v.get("volumeInfo") or {}
        title = (info.get("title") or "").strip()
        url = info.get("infoLink") or info.get("canonicalVolumeLink") or ""
        if not title or not url:
            continue
        isbn = next((i.get("identifier") for i in (info.get("industryIdentifiers") or [])
                     if i.get("type") == "ISBN_13"), None)
        hits.append(SourceHit(
            title=title,
            url=url,
            identifiers={"isbn": isbn} if isbn else {},
            snippet=(info.get("description") or "")[:300],
            publishedAt=info.get("publishedDate"),
            authors=[{"name": a} for a in (info.get("authors") or [])],
            venue=info.get("publisher") or "",
            sourceType="book",
            tierHint="secondary",
            connector="books",
        ))
    return hits


def parse_ndl_sru(xml_text: str) -> list[SourceHit]:
    """Best-effort Dublin-Core extraction from an NDL SRU searchRetrieve response."""
    hits = []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []
    for title_el in root.iter(f"{_DC}title"):
        record = title_el
        title = (title_el.text or "").strip()
        if not title:
            continue
        # creator/identifier live as siblings under the same parent record.
        parent = _find_parent(root, title_el)
        creators, url = [], ""
        if parent is not None:
            for c in parent.iter(f"{_DC}creator"):
                if c.text:
                    creators.append({"name": c.text.strip()})
            for ident in parent.iter(f"{_DC}identifier"):
                if ident.text and ident.text.startswith("http"):
                    url = ident.text.strip()
                    break
        hits.append(SourceHit(
            title=title, url=url or f"https://ndlsearch.ndl.go.jp/search?cs=bib&keyword={title}",
            authors=creators, sourceType="book", tierHint="secondary",
            connector="books", venue="NDL",
        ))
    return hits


def _find_parent(root: ET.Element, child: ET.Element):
    for parent in root.iter():
        if child in list(parent):
            return parent
    return None


class BooksConnector(HttpConnector):
    name = "books"

    def _search(self, q: StrategyQuery) -> list[SourceHit]:
        n = min(max(q.maxResults, 1), 20)
        hits = parse_google_books(self._get_json(GOOGLE_BOOKS_URL, params={
            "q": q.query, "maxResults": n, "printType": "books"}))
        try:
            resp = self._get(NDL_SRU_URL, params={
                "operation": "searchRetrieve", "query": q.query,
                "recordSchema": "dcndl", "maximumRecords": n})
            hits += parse_ndl_sru(resp.text)
        except Exception as exc:  # noqa: BLE001 — NDL is additive
            log.warning("ndl sru failed", extra={"fields": {"error": str(exc)}})
        return hits
