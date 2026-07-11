"""URL canonicalization and dedup hashing.

Item doc IDs are sha256(canonical_url)[:32] so re-collecting the same URL is a
no-op. titleNormHash catches near-duplicates (same story from another outlet).
"""

import hashlib
import re
import unicodedata
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

_TRACKING_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "utm_id", "gclid", "fbclid", "igshid", "mc_cid", "mc_eid", "ref",
    "cmpid", "smid", "s", "src", "share", "spm",
}


def canonicalize_url(url: str) -> str:
    url = url.strip()
    scheme, netloc, path, query, _fragment = urlsplit(url)
    scheme = (scheme or "https").lower()
    netloc = netloc.lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]
    if netloc.endswith(":80") and scheme == "http":
        netloc = netloc[:-3]
    if netloc.endswith(":443") and scheme == "https":
        netloc = netloc[:-4]
    params = [
        (k, v)
        for k, v in parse_qsl(query, keep_blank_values=True)
        if k.lower() not in _TRACKING_PARAMS
    ]
    params.sort()
    if path != "/":
        path = path.rstrip("/")
    return urlunsplit((scheme, netloc, path or "/", urlencode(params), ""))


def item_doc_id(canonical_url: str) -> str:
    return hashlib.sha256(canonical_url.encode("utf-8")).hexdigest()[:32]


_WORD_RE = re.compile(r"[a-z0-9가-힣぀-ヿ一-鿿]+")


def normalize_title(title: str) -> str:
    """Lowercased, accent-stripped, sorted word bag — order-insensitive."""
    title = unicodedata.normalize("NFKD", title).lower()
    words = sorted(set(_WORD_RE.findall(title)))
    return " ".join(words)


def title_norm_hash(title: str) -> str:
    return hashlib.sha256(normalize_title(title).encode("utf-8")).hexdigest()[:16]
