"""P2: guarded fetcher (SSRF / robots / size / content-type / Wayback) + extractor."""

import httpx
import respx

from app.research.fetch import extract_text
from app.research.fetch.fetcher import HTML_CAP, Fetcher, is_safe_url


def _public(_host):
    return ["93.184.216.34"]  # pretend every test host resolves to a public IP


def _fetcher(**kw):
    kw.setdefault("resolve", _public)
    kw.setdefault("respect_robots", False)
    kw.setdefault("sleep", lambda *_a, **_k: None)
    kw.setdefault("rps", 0)
    return Fetcher(**kw)


# ---------- SSRF guard ----------

def test_is_safe_url_rejects_scheme_and_internal_addresses():
    assert is_safe_url("ftp://example.com/x", _public) is False
    assert is_safe_url("http://127.0.0.1/x") is False          # loopback literal
    assert is_safe_url("http://10.0.0.1/x") is False           # private literal
    assert is_safe_url("http://169.254.169.254/latest") is False  # link-local (cloud metadata)
    assert is_safe_url("http://localhost/x", lambda h: ["127.0.0.1"]) is False  # resolves loopback
    assert is_safe_url("https://example.com/x", _public) is True


def test_fetch_blocks_ssrf_without_network():
    # No respx route registered — if it tried to fetch, respx would error.
    assert _fetcher().fetch("http://169.254.169.254/latest/meta-data") is None


# ---------- normal fetch + guards ----------

@respx.mock
def test_fetch_success_returns_bytes_and_mime():
    respx.get(host="ex.org", path="/a").mock(return_value=httpx.Response(
        200, html="<html><body>hi</body></html>"))
    res = _fetcher().fetch("https://ex.org/a")
    assert res is not None and res.mimeType == "text/html"
    assert b"hi" in res.data and res.viaArchive is False


@respx.mock
def test_fetch_rejects_disallowed_content_type():
    respx.get(host="ex.org", path="/img").mock(return_value=httpx.Response(
        200, content=b"\x89PNG", headers={"content-type": "image/png"}))
    assert _fetcher().fetch("https://ex.org/img") is None


@respx.mock
def test_fetch_rejects_oversize_body():
    respx.get(host="ex.org", path="/big").mock(return_value=httpx.Response(
        200, headers={"content-type": "text/html"}, content=b"x" * (HTML_CAP + 1)))
    assert _fetcher().fetch("https://ex.org/big") is None


@respx.mock
def test_fetch_honours_robots_disallow():
    respx.get(host="ex.org", path="/robots.txt").mock(return_value=httpx.Response(
        200, text="User-agent: *\nDisallow: /secret"))
    respx.get(host="ex.org", path="/secret/p").mock(return_value=httpx.Response(200, html="<p>x</p>"))
    respx.get(host="ex.org", path="/open/p").mock(return_value=httpx.Response(200, html="<p>ok</p>"))
    f = _fetcher(respect_robots=True)
    assert f.fetch("https://ex.org/secret/p") is None
    assert f.fetch("https://ex.org/open/p") is not None


@respx.mock
def test_fetch_per_domain_cap():
    respx.get(host="ex.org").mock(return_value=httpx.Response(200, html="<p>x</p>"))
    f = _fetcher()
    for i in range(10):
        assert f.fetch(f"https://ex.org/p{i}") is not None
    assert f.fetch("https://ex.org/p11") is None  # 11th over the per-domain cap


@respx.mock
def test_fetch_dead_link_falls_back_to_wayback():
    respx.get(host="dead.org", path="/gone").mock(return_value=httpx.Response(404))
    respx.get(host="archive.org", path="/wayback/available").mock(return_value=httpx.Response(
        200, json={"archived_snapshots": {"closest": {
            "available": True, "url": "https://web.archive.org/snap/gone"}}}))
    respx.get(host="web.archive.org").mock(return_value=httpx.Response(
        200, html="<html><body>archived copy</body></html>"))
    res = _fetcher().fetch("https://dead.org/gone")
    assert res is not None and res.viaArchive is True and b"archived copy" in res.data


# ---------- extraction ----------

def test_extract_html_pulls_main_text():
    html = (
        "<html><head><title>t</title></head><body>"
        "<nav>menu junk</nav>"
        "<article><h1>Headline</h1>"
        "<p>The Diet debated imperial war responsibility in December 1988 at length.</p>"
        "<p>Multiple members raised the question of accountability and record-keeping.</p>"
        "</article><footer>copyright</footer></body></html>"
    ).encode("utf-8")
    text = extract_text.extract(html, "text/html")
    assert "imperial war responsibility" in text
    assert "menu junk" not in text  # boilerplate stripped


def test_extract_plain_text_passthrough():
    assert extract_text.extract(b"just plain text", "text/plain") == "just plain text"


def test_extract_pdf_garbage_returns_empty_not_crash():
    assert extract_text.extract(b"%PDF-not-really", "application/pdf") == ""
