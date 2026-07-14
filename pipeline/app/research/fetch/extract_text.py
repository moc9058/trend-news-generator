"""Main-text extraction from fetched bytes (design §9.1 P2).

trafilatura strips HTML boilerplate to the article body; pypdf pulls text from
PDFs. Output is capped so a single huge source can't blow the extraction prompt.
Extracted content is UNTRUSTED input — the R4 prompt is hardened against injected
instructions and the extract phase holds no tool permissions (design §6.6).
"""

import io

import trafilatura
from pypdf import PdfReader

from app.utils.logging import get_logger

log = get_logger(__name__)

MAX_CHARS = 40_000


def extract(data: bytes, mime: str) -> str:
    """Dispatch on content type; always returns a (possibly empty) string."""
    kind = (mime or "").split(";")[0].strip().lower()
    if kind == "application/pdf":
        return _extract_pdf(data)[:MAX_CHARS]
    if kind == "text/plain":
        return data.decode("utf-8", "replace").strip()[:MAX_CHARS]
    return _extract_html(data)[:MAX_CHARS]


def _extract_html(data: bytes) -> str:
    html = data.decode("utf-8", "replace")
    try:
        text = trafilatura.extract(
            html, output_format="txt", include_comments=False,
            include_tables=True, favor_recall=True,
        )
    except Exception as exc:  # noqa: BLE001 — extraction is best-effort
        log.warning("html extract failed", extra={"fields": {"error": str(exc)}})
        text = None
    return (text or "").strip()


def _extract_pdf(data: bytes) -> str:
    try:
        reader = PdfReader(io.BytesIO(data))
        return "\n".join((page.extract_text() or "") for page in reader.pages).strip()
    except Exception as exc:  # noqa: BLE001 — corrupt/encrypted PDF → empty
        log.warning("pdf extract failed", extra={"fields": {"error": str(exc)}})
        return ""
