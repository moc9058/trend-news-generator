"""arXiv (Atom via the rss collector) and IEEE Xplore collectors."""

from pathlib import Path

from app.collectors.ieee_xplore import parse_articles
from app.collectors.rss import parse_feed

FIXTURES = Path(__file__).parent / "fixtures"


def test_arxiv_atom_parses_through_feed_collector():
    items = parse_feed((FIXTURES / "arxiv_atom.xml").read_bytes())
    assert len(items) == 2
    assert items[0].title == "Scaling Laws for Agentic Reasoning"
    assert items[0].url == "http://arxiv.org/abs/2607.01234v1"
    assert items[0].publishedAt is not None
    assert "inference-time compute" in items[0].summary


def test_ieee_parse_articles():
    payload = {
        "total_records": 2,
        "articles": [
            {
                "title": "A Survey of Edge AI Accelerators",
                "abstract": "We survey recent accelerator designs.",
                "html_url": "https://ieeexplore.ieee.org/document/1234567",
                "publication_date": "1 June 2026",
            },
            {
                "title": "No URL entry is dropped",
                "abstract": "x",
                "publication_date": "2026",
            },
        ],
    }
    items = parse_articles(payload)
    assert len(items) == 1
    assert items[0].url == "https://ieeexplore.ieee.org/document/1234567"
    assert items[0].publishedAt.year == 2026


def test_ieee_collector_skips_without_key(monkeypatch):
    from app.collectors.ieee_xplore import IeeeXploreCollector
    from app.config import get_settings
    from app.models import Source, SourceType

    monkeypatch.setattr(get_settings(), "ieee_api_key", "")
    collector = IeeeXploreCollector()
    source = Source(id="s", categoryId="c", type=SourceType.ieee_xplore, query="ai")
    assert collector.collect(source) == []
