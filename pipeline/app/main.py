"""pipeline-api: the small authenticated surface the admin UI calls for actions
(approve+publish, per-channel retry, run-a-job-now). Deployed with
--no-allow-unauthenticated; Cloud Run IAM does authn (admin-sa has run.invoker),
so there is no app-level auth here. All reads/writes for display go straight
from the admin UI to Firestore."""

import google.auth
import google.auth.transport.requests
import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from app.config import get_settings
from app.models import ChannelStatus, PostStatus
from app.publishers.base import publish_post
from app.repo import posts
from app.utils.logging import get_logger

log = get_logger(__name__)
app = FastAPI(title="trend-news pipeline-api")

JOB_MODULES = {
    "collect": "app.jobs.collect",
    "generate_short": "app.jobs.generate_short",
    "generate_article": "app.jobs.generate_article",
    "cleanup_drafts": "app.jobs.cleanup_drafts",
    "refresh_threads_token": "app.jobs.refresh_threads_token",
    "seed": "app.jobs.seed",
}


class PublishRequest(BaseModel):
    approvedBy: str = ""
    channels: list[str] = []  # empty = all enabled channels


class RetryRequest(BaseModel):
    channel: str


@app.get("/healthz")
def healthz() -> dict:
    return {"ok": True}


@app.post("/api/posts/{post_id}/publish")
def publish(post_id: str, req: PublishRequest) -> dict:
    post = posts.get(post_id)
    if post is None:
        raise HTTPException(404, "post not found")
    if post.status in (PostStatus.published, PostStatus.publishing):
        raise HTTPException(409, f"post is {post.status.value}")

    # channel selection from the drafts page: disable de-selected channels
    if req.channels:
        for name, state in post.channels.items():
            if name not in req.channels and state.status == ChannelStatus.pending:
                state.enabled = False
                state.status = ChannelStatus.skipped
                posts.update_channel(post_id, name, state)

    posts.update_fields(post_id, {
        "approvedBy": req.approvedBy,
        "status": PostStatus.approved.value,
    })
    result = publish_post(post_id)
    return {
        "status": result.status.value,
        "channels": {k: v.status.value for k, v in result.channels.items()},
    }


@app.post("/api/posts/{post_id}/retry-channel")
def retry_channel(post_id: str, req: RetryRequest) -> dict:
    post = posts.get(post_id)
    if post is None:
        raise HTTPException(404, "post not found")
    state = post.channels.get(req.channel)
    if state is None:
        raise HTTPException(400, f"unknown channel {req.channel}")
    if state.status != ChannelStatus.failed:
        raise HTTPException(409, f"channel is {state.status.value}, not failed")

    state.status = ChannelStatus.pending
    state.error = ""
    posts.update_channel(post_id, req.channel, state)
    result = publish_post(post_id, only_channel=req.channel)
    return {
        "status": result.status.value,
        "channel": result.channels[req.channel].status.value,
        "error": result.channels[req.channel].error,
    }


def _cloud_run_job_name(api_name: str) -> str:
    """`generate_short` -> `job-generate-short` (the deployed Cloud Run Job)."""
    return "job-" + api_name.replace("_", "-")


def _trigger_job(api_name: str) -> None:
    """Start a real Cloud Run Job execution (fire-and-forget).

    Unlike an in-process run, the job runs on its own Cloud Run Job instance
    with the job's own memory/timeout/retry settings, so a long collect or
    generate finishes reliably even if this API instance scales down.
    """
    settings = get_settings()
    creds, _ = google.auth.default(
        scopes=["https://www.googleapis.com/auth/cloud-platform"],
    )
    creds.refresh(google.auth.transport.requests.Request())
    url = (
        f"https://run.googleapis.com/v2/projects/{settings.project_id}"
        f"/locations/{settings.region}/jobs/{_cloud_run_job_name(api_name)}:run"
    )
    resp = httpx.post(
        url,
        headers={"Authorization": f"Bearer {creds.token}"},
        timeout=30,
    )
    resp.raise_for_status()


@app.post("/api/jobs/{name}/run", status_code=202)
def run_job(name: str) -> dict:
    if name not in JOB_MODULES:
        raise HTTPException(400, f"unknown job {name}")
    job_name = _cloud_run_job_name(name)
    try:
        _trigger_job(name)
    except httpx.HTTPStatusError as exc:
        detail = exc.response.text[:300]
        log.error("job trigger failed", extra={"fields": {
            "job": job_name, "status": exc.response.status_code, "body": detail}})
        raise HTTPException(502, f"failed to start {job_name}: {detail}")
    except Exception as exc:  # noqa: BLE001 — surface any auth/network failure
        log.error("job trigger error", extra={"fields": {"job": job_name, "error": str(exc)}})
        raise HTTPException(502, f"failed to start {job_name}: {exc}")
    log.info("job triggered", extra={"fields": {"job": job_name}})
    return {"accepted": True, "job": job_name}
