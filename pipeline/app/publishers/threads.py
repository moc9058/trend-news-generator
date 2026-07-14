"""Threads Graph API publisher: create container → poll status → publish.

The container id is persisted on the post before publish so a crash between
the two phases can be recovered without creating a duplicate.
"""

import time

import httpx

from app.config import get_settings
from app.utils.logging import get_logger
from app.utils.retry import PermanentPublishError, api_retry

log = get_logger(__name__)

GRAPH = "https://graph.threads.net/v1.0"
POLL_INTERVAL_S = 2
POLL_MAX_ATTEMPTS = 15


@api_retry
def create_container(text: str, image_url: str = "") -> str:
    settings = get_settings()
    params: dict = {"access_token": settings.threads_access_token, "text": text}
    if image_url:
        params.update({"media_type": "IMAGE", "image_url": image_url})
    else:
        params["media_type"] = "TEXT"
    with httpx.Client(timeout=30) as client:
        resp = client.post(f"{GRAPH}/{settings.threads_user_id}/threads", params=params)
        resp.raise_for_status()
        return resp.json()["id"]


def wait_until_ready(container_id: str) -> None:
    settings = get_settings()
    with httpx.Client(timeout=30) as client:
        for _ in range(POLL_MAX_ATTEMPTS):
            resp = client.get(
                f"{GRAPH}/{container_id}",
                params={
                    "fields": "status,error_message",
                    "access_token": settings.threads_access_token,
                },
            )
            resp.raise_for_status()
            payload = resp.json()
            status = payload.get("status")
            if status == "FINISHED":
                return
            if status == "ERROR":
                raise PermanentPublishError(
                    f"threads container error: {payload.get('error_message')}"
                )
            time.sleep(POLL_INTERVAL_S)
    raise PermanentPublishError(f"threads container {container_id} never became ready")


@api_retry
def publish_container(container_id: str) -> str:
    """Returns the published thread media id."""
    settings = get_settings()
    with httpx.Client(timeout=30) as client:
        resp = client.post(
            f"{GRAPH}/{settings.threads_user_id}/threads_publish",
            params={
                "creation_id": container_id,
                "access_token": settings.threads_access_token,
            },
        )
        resp.raise_for_status()
        media_id = resp.json()["id"]
        log.info("threads published", extra={"fields": {"id": media_id}})
        return media_id


@api_retry
def delete(media_id: str) -> None:
    """Delete a published thread (Threads API DELETE /{media-id})."""
    settings = get_settings()
    with httpx.Client(timeout=30) as client:
        resp = client.delete(
            f"{GRAPH}/{media_id}",
            params={"access_token": settings.threads_access_token},
        )
        if resp.status_code == 404:  # already gone remotely
            return
        resp.raise_for_status()
    log.info("threads deleted", extra={"fields": {"id": media_id}})


@api_retry
def refresh_long_lived_token(current_token: str) -> dict:
    """Returns {"access_token": ..., "expires_in": seconds}."""
    with httpx.Client(timeout=30) as client:
        resp = client.get(
            f"{GRAPH.rsplit('/', 1)[0]}/refresh_access_token",
            params={"grant_type": "th_refresh_token", "access_token": current_token},
        )
        resp.raise_for_status()
        return resp.json()
