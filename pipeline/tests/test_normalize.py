from app.normalize import canonicalize_url, item_doc_id, normalize_title, title_norm_hash


def test_strips_tracking_params():
    assert (
        canonicalize_url("https://example.com/a?utm_source=x&utm_medium=y&id=1")
        == "https://example.com/a?id=1"
    )


def test_strips_www_fragment_and_trailing_slash():
    assert canonicalize_url("https://www.Example.com/news/") == "https://example.com/news"
    assert canonicalize_url("https://example.com/a#section") == "https://example.com/a"


def test_sorts_query_params():
    assert (
        canonicalize_url("https://example.com/a?b=2&a=1")
        == canonicalize_url("https://example.com/a?a=1&b=2")
    )


def test_root_path_preserved():
    assert canonicalize_url("https://example.com/") == "https://example.com/"


def test_doc_id_stable_and_short():
    a = item_doc_id("https://example.com/a")
    assert a == item_doc_id("https://example.com/a")
    assert len(a) == 32


def test_title_normalization_order_and_case_insensitive():
    assert normalize_title("Fed Raises Rates") == normalize_title("rates raises fed")
    assert title_norm_hash("Fed Raises Rates!") == title_norm_hash("FED raises rates")


def test_title_hash_differs_for_different_stories():
    assert title_norm_hash("Fed raises rates") != title_norm_hash("BOJ cuts rates")


def test_cjk_titles():
    assert title_norm_hash("日銀が利上げを決定") == title_norm_hash("日銀が利上げを決定！")
