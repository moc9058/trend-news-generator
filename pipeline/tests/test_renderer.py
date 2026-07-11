from app.publishers.renderer import (
    X_LIMIT,
    append_url,
    fits_threads,
    fits_x,
    split_for_x_thread,
    strip_urls,
    x_weighted_length,
)


def test_ascii_weight_is_one():
    assert x_weighted_length("hello") == 5


def test_cjk_weight_is_two():
    assert x_weighted_length("日本語") == 6
    assert x_weighted_length("한국어") == 6


def test_url_counts_as_23():
    assert x_weighted_length("https://example.com/very/long/path/that/goes/on") == 23
    assert x_weighted_length("go https://e.co x") == 3 + 23 + 2


def test_fits_x_boundary():
    assert fits_x("a" * 280)
    assert not fits_x("a" * 281)
    assert fits_x("日" * 140)
    assert not fits_x("日" * 141)


def test_fits_threads():
    assert fits_threads("a" * 500)
    assert not fits_threads("a" * 501)


def test_split_short_text_is_single_part():
    assert split_for_x_thread("short") == ["short"]


def test_split_long_text_numbered_and_within_limit():
    text = "This is a sentence. " * 40
    parts = split_for_x_thread(text)
    assert len(parts) > 1
    for i, part in enumerate(parts, start=1):
        assert x_weighted_length(part) <= X_LIMIT
        assert part.endswith(f"({i}/{len(parts)})")


def test_split_cjk_long_text():
    text = "これは長い文章です。" * 30
    parts = split_for_x_thread(text)
    assert len(parts) > 1
    assert all(x_weighted_length(p) <= X_LIMIT for p in parts)


def test_strip_urls():
    assert strip_urls("check https://example.com now") == "check now"


def test_append_url_trims_to_fit():
    text = "a" * 279
    result = append_url(text, "https://notion.so/page", fits_x)
    assert fits_x(result)
    assert result.endswith("https://notion.so/page")
