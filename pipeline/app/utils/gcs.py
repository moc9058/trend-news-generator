"""GCS helpers: store collected images, mint V4 signed URLs for Threads.

Signed URLs require pipeline-sa to hold roles/iam.serviceAccountTokenCreator on
itself (granted in infra/00-bootstrap.sh) because Cloud Run has no private key.
"""

import datetime
from functools import lru_cache

import google.auth
from google.auth import impersonated_credentials
from google.cloud import storage

from app.config import get_settings


@lru_cache
def _client() -> storage.Client:
    return storage.Client(project=get_settings().project_id)


def upload_bytes(path: str, data: bytes, mime: str) -> str:
    bucket = _client().bucket(get_settings().gcs_bucket)
    blob = bucket.blob(path)
    blob.upload_from_string(data, content_type=mime)
    return path


def download_bytes(path: str) -> bytes:
    bucket = _client().bucket(get_settings().gcs_bucket)
    return bucket.blob(path).download_as_bytes()


def signed_url(path: str, minutes: int = 30) -> str:
    settings = get_settings()
    creds, _ = google.auth.default()
    sa_email = settings.pipeline_service_account or getattr(
        creds, "service_account_email", ""
    )
    signing_creds = impersonated_credentials.Credentials(
        source_credentials=creds,
        target_principal=sa_email,
        target_scopes=["https://www.googleapis.com/auth/devstorage.read_only"],
    )
    bucket = _client().bucket(settings.gcs_bucket)
    return bucket.blob(path).generate_signed_url(
        version="v4",
        expiration=datetime.timedelta(minutes=minutes),
        credentials=signing_creds,
    )
