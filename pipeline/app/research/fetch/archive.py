"""GCS snapshot archival for evidence (design §4.4, §4.5, §6.6).

Every fetched source is stored to research/{runId}/snapshots/{urlHash}.{ext} with
its sha256 recorded on the EvidenceRecord. That sha256 is the fixed reference
point for the R8 citecheck: a quoted string must exist in these exact bytes, so a
hallucinated citation cannot survive (design §8.1 引用妥当性 ≥98%).
"""

import hashlib

from app.config import get_settings
from app.research.schemas import Archive
from app.utils import gcs

# content-type → snapshot file extension
_EXT = {
    "text/html": "html",
    "application/xhtml+xml": "html",
    "application/pdf": "pdf",
    "text/plain": "txt",
}


def _ext_for(mime: str) -> str:
    return _EXT.get((mime or "").split(";")[0].strip(), "txt")


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def snapshot(run_id: str, url_hash: str, data: bytes, mime: str,
             fetched_by: str) -> Archive:
    """Upload fetched bytes and return the Archive metadata (gcsUri + sha256)."""
    path = f"research/{run_id}/snapshots/{url_hash}.{_ext_for(mime)}"
    gcs.upload_bytes(path, data, mime)
    return Archive(
        gcsUri=f"gs://{get_settings().gcs_bucket}/{path}",
        sha256=sha256_hex(data),
        mimeType=mime,
        fetchedBy=fetched_by,
    )


def verify(archive: Archive, data: bytes) -> bool:
    """True iff `data` matches the archived sha256 — the citecheck integrity gate."""
    return bool(archive.sha256) and sha256_hex(data) == archive.sha256
