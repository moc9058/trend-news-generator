"""Best-effort enrichment of a collected item: fetch the article page for
og:image and readable text. Failures never block collection."""

import httpx
from bs4 import BeautifulSoup

from app.utils.logging import get_logger

log = get_logger(__name__)

MAX_CONTENT_CHARS = 10_000
MAX_IMAGE_BYTES = 8 * 1024 * 1024
_IMAGE_MIMES = {"image/jpeg", "image/png", "image/webp", "image/gif"}


def fetch_page(url: str, client: httpx.Client) -> tuple[str, str]:
    """Returns (og_image_url, content_text); empty strings on any failure."""
    try:
        resp = client.get(url, timeout=15)
        resp.raise_for_status()
        if "html" not in resp.headers.get("content-type", ""):
            return "", ""
        soup = BeautifulSoup(resp.text, "html.parser")
        og = soup.find("meta", property="og:image")
        image_url = (og.get("content") or "").strip() if og else ""
        for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
            tag.decompose()
        text = " ".join(soup.get_text(separator=" ").split())
        return image_url, text[:MAX_CONTENT_CHARS]
    except Exception as exc:
        log.info("enrich failed", extra={"fields": {"url": url, "error": str(exc)}})
        return "", ""


def fetch_image(url: str, client: httpx.Client) -> tuple[bytes, str] | None:
    """Returns (bytes, mime) or None."""
    try:
        resp = client.get(url, timeout=15)
        resp.raise_for_status()
        mime = resp.headers.get("content-type", "").split(";")[0].strip()
        if mime not in _IMAGE_MIMES or len(resp.content) > MAX_IMAGE_BYTES:
            return None
        return resp.content, mime
    except Exception:
        return None
