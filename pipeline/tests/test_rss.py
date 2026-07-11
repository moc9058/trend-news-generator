from pathlib import Path

from app.collectors.rss import parse_feed

FIXTURE = Path(__file__).parent / "fixtures" / "sample_feed.xml"


def test_parse_feed_extracts_items():
    items = parse_feed(FIXTURE.read_bytes())
    assert len(items) == 2  # empty-title entry dropped
    first = items[0]
    assert first.title == "AI chip breakthrough announced"
    assert first.url == "https://example.com/news/ai-chip?utm_source=rss"
    assert first.publishedAt is not None
    assert first.publishedAt.year == 2026
    assert "inference speed" in first.summary
    assert first.imageUrl == "https://example.com/img/chip.jpg"


def test_parse_feed_without_image():
    items = parse_feed(FIXTURE.read_bytes())
    assert items[1].imageUrl == ""
