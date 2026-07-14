"""P2: source connectors — respx HTTP tests (normal / 429-retry / fallback chain)
and fake-genai tests for the grounded connectors."""

from types import SimpleNamespace

import httpx
import pytest
import respx

import app.research.sources.academic as academic_mod
import app.research.sources.ieee as ieee_mod
from app.research.schemas import StrategyQuery
from app.research.sources.academic import AcademicConnector
from app.research.sources.base import HttpConnector
from app.research.sources.books import BooksConnector
from app.research.sources.gov_docs import GovDocsConnector
from app.research.sources.ieee import IeeeConnector
from app.research.sources.kokkai import KokkaiConnector
from app.research.sources.news import NewsConnector
from app.research.sources.web_grounded import WebGroundedConnector


@pytest.fixture(autouse=True)
def _no_retry_sleep(monkeypatch):
    # tenacity backoff uses time.sleep — neutralise it so retry tests stay fast.
    monkeypatch.setattr("time.sleep", lambda *_a, **_k: None)


def _q(query="天皇 戦争責任", **kw):
    return StrategyQuery(rqId="rq1", query=query, **kw)


# ---------- kokkai (attaches full text) ----------

@respx.mock
def test_kokkai_parses_speech_and_attaches_content():
    respx.get(host="kokkai.ndl.go.jp").mock(return_value=httpx.Response(200, json={
        "numberOfRecords": 1,
        "speechRecord": [{
            "speechID": "S1", "issueID": "110214889X00319881213", "session": 102,
            "nameOfHouse": "参議院", "nameOfMeeting": "内閣委員会", "issue": "第3号",
            "date": "1988-12-13", "speaker": "答弁者", "speakerRole": "国務大臣",
            "speech": "「責任」という言葉について申し上げます。" * 20,
            "speechURL": "https://kokkai.ndl.go.jp/txt/1", "meetingURL": "https://kokkai.ndl.go.jp/m/1",
        }],
    }))
    hits = KokkaiConnector()._search(_q())
    assert len(hits) == 1
    h = hits[0]
    assert h.sourceType == "parliamentary_record" and h.tierHint == "primary"
    assert h.identifiers["kokkaiIssueId"] == "110214889X00319881213"
    assert h.contentText.startswith("「責任」")  # full text attached → R4 skips fetch
    assert h.authors[0].name == "答弁者"


# ---------- academic fallback chain (SS → OpenAlex → Crossref) + arXiv ----------

def _arxiv_atom():
    return (
        '<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom">'
        '<entry><id>http://arxiv.org/abs/1706.03762</id>'
        '<title>Attention Is All You Need</title>'
        '<summary>The dominant sequence transduction models...</summary>'
        '<published>2017-06-12T00:00:00Z</published>'
        '<author><name>Vaswani, A.</name></author></entry></feed>'
    )


@respx.mock
def test_academic_uses_semantic_scholar_when_it_returns_hits():
    respx.get(host="api.semanticscholar.org").mock(return_value=httpx.Response(200, json={
        "data": [{"title": "Attention Is All You Need", "url": "https://arxiv.org/abs/1706.03762",
                  "year": 2017, "citationCount": 150000, "venue": "NeurIPS",
                  "externalIds": {"ArXiv": "1706.03762", "DOI": "10.48550/arXiv.1706.03762"},
                  "authors": [{"name": "Vaswani, A."}]}]}))
    respx.get(host="export.arxiv.org").mock(return_value=httpx.Response(200, text=_arxiv_atom()))
    # OpenAlex / Crossref must NOT be hit when SS succeeds
    oa = respx.get(host="api.openalex.org").mock(return_value=httpx.Response(200, json={"results": []}))
    hits = AcademicConnector()._search(_q("transformer"))
    ss_hits = [h for h in hits if h.venue == "NeurIPS"]
    assert ss_hits and ss_hits[0].citationCount == 150000
    assert any(h.venue == "arXiv" for h in hits)  # arXiv is additive
    assert not oa.called


@respx.mock
def test_academic_falls_back_to_openalex_when_ss_empty():
    respx.get(host="api.semanticscholar.org").mock(return_value=httpx.Response(200, json={"data": []}))
    respx.get(host="api.openalex.org").mock(return_value=httpx.Response(200, json={"results": [{
        "title": "A history paper", "publication_year": 2001,
        "doi": "https://doi.org/10.1/x", "cited_by_count": 42,
        "primary_location": {"landing_page_url": "https://ex.org/p", "source": {"display_name": "J. Hist"}},
        "authorships": [{"author": {"display_name": "Historian, B."}}]}]}))
    respx.get(host="export.arxiv.org").mock(return_value=httpx.Response(200, text="<feed/>"))
    hits = AcademicConnector()._search(_q())
    assert any(h.venue == "J. Hist" and h.citationCount == 42 for h in hits)


@respx.mock
def test_academic_falls_through_to_crossref_on_error(monkeypatch):
    # SS errors (persistent 500 → retries exhausted → exception → fallback);
    # OpenAlex also empty; Crossref supplies the hit.
    respx.get(host="api.semanticscholar.org").mock(return_value=httpx.Response(500))
    respx.get(host="api.openalex.org").mock(return_value=httpx.Response(200, json={"results": []}))
    respx.get(host="api.crossref.org").mock(return_value=httpx.Response(200, json={"message": {"items": [{
        "title": ["Crossref result"], "DOI": "10.2/y", "URL": "https://doi.org/10.2/y",
        "published": {"date-parts": [[1999]]}, "is-referenced-by-count": 7,
        "container-title": ["Journal Z"], "author": [{"given": "C.", "family": "Ross"}]}]}}))
    respx.get(host="export.arxiv.org").mock(return_value=httpx.Response(200, text="<feed/>"))
    hits = AcademicConnector()._search(_q())
    assert any(h.venue == "Journal Z" and h.identifiers.get("doi") == "10.2/y" for h in hits)


@respx.mock
def test_academic_retries_429_then_succeeds():
    route = respx.get(host="api.semanticscholar.org").mock(side_effect=[
        httpx.Response(429), httpx.Response(200, json={"data": [{
            "title": "Retried OK", "url": "https://x/1", "year": 2020,
            "externalIds": {}, "authors": []}]})])
    respx.get(host="export.arxiv.org").mock(return_value=httpx.Response(200, text="<feed/>"))
    hits = AcademicConnector()._search(_q())
    assert route.call_count == 2  # one 429, one success
    assert any(h.title == "Retried OK" for h in hits)


# ---------- ieee (needs key) ----------

@respx.mock
def test_ieee_parses_articles(monkeypatch):
    monkeypatch.setattr(ieee_mod, "get_settings",
                        lambda: SimpleNamespace(ieee_api_key="k"))
    respx.get(host="ieeexploreapi.ieee.org").mock(return_value=httpx.Response(200, json={
        "articles": [{"title": "A DNN paper", "html_url": "https://ieee.org/a1",
                      "abstract": "abstract text", "publication_date": "1 June 2020",
                      "publication_title": "IEEE TPAMI", "doi": "10.1109/x",
                      "authors": {"authors": [{"full_name": "Doe, J."}]}}]}))
    hits = IeeeConnector()._search(_q("semiconductor"))
    assert hits[0].venue == "IEEE TPAMI" and hits[0].identifiers["doi"] == "10.1109/x"
    assert hits[0].authors[0].name == "Doe, J."


def test_ieee_skips_without_key(monkeypatch):
    monkeypatch.setattr(ieee_mod, "get_settings",
                        lambda: SimpleNamespace(ieee_api_key=""))
    assert IeeeConnector()._search(_q()) == []


# ---------- books (Google Books + NDL SRU additive) ----------

@respx.mock
def test_books_parses_google_books():
    respx.get(host="www.googleapis.com").mock(return_value=httpx.Response(200, json={
        "items": [{"volumeInfo": {"title": "昭和天皇", "authors": ["著者"],
                                  "publishedDate": "1990", "publisher": "出版社",
                                  "infoLink": "https://books.google/1",
                                  "industryIdentifiers": [{"type": "ISBN_13", "identifier": "9781234567890"}],
                                  "description": "研究書"}}]}))
    respx.get(host="ndlsearch.ndl.go.jp").mock(return_value=httpx.Response(200, text="<x/>"))
    hits = BooksConnector()._search(_q("昭和天皇"))
    assert hits[0].sourceType == "book" and hits[0].identifiers["isbn"] == "9781234567890"
    assert hits[0].venue == "出版社"


# ---------- grounded connectors (fake genai client) ----------

class _FakeModels:
    def __init__(self, text):
        self.text = text
        self.last_contents = None

    def generate_content(self, model, contents, config):
        self.last_contents = contents
        return SimpleNamespace(text=self.text, candidates=[])


class _FakeGenai:
    def __init__(self, text):
        self.models = _FakeModels(text)


_GROUNDED_JSON = ('[{"title":"公文書A","url":"https://e-gov.go.jp/law/1",'
                  '"summary":"official","published":"2020-01-01"}]')


def test_web_grounded_returns_hits_with_tier():
    conn = WebGroundedConnector(client=_FakeGenai(_GROUNDED_JSON))
    hits = conn.search(_q("憲法"))
    assert hits[0].connector == "web_grounded" and hits[0].tierHint == "tertiary"
    assert hits[0].sourceType == "web" and hits[0].url == "https://e-gov.go.jp/law/1"


def test_gov_docs_applies_site_filters_and_primary_tier():
    fake = _FakeGenai(_GROUNDED_JSON)
    conn = GovDocsConnector(client=fake)
    hits = conn.search(_q("行政手続法"))
    assert hits[0].sourceType == "official_document" and hits[0].tierHint == "primary"
    assert "site:go.jp" in fake.models.last_contents  # domain restriction applied


def test_news_connector_marks_quality_news():
    conn = NewsConnector(client=_FakeGenai(_GROUNDED_JSON))
    hits = conn.search(_q("選挙"))
    assert hits[0].sourceType == "quality_news" and hits[0].tierHint == "secondary"


# ---------- base: circuit breaker ----------

class _AlwaysFails(HttpConnector):
    name = "boom"

    def _search(self, q):
        raise RuntimeError("upstream down")


def test_circuit_breaker_disables_after_consecutive_failures():
    conn = _AlwaysFails()
    for _ in range(4):
        assert conn.search(_q()) == [] and conn.disabled is False
    assert conn.search(_q()) == [] and conn.disabled is True  # 5th → tripped
