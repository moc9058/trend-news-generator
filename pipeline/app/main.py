"""pipeline-api: the small authenticated surface the admin UI calls for actions
(approve+publish, per-channel retry, run-a-job-now). Deployed with
--no-allow-unauthenticated; Cloud Run IAM does authn (admin-sa has run.invoker),
so there is no app-level auth here. All reads/writes for display go straight
from the admin UI to Firestore."""

import importlib
from datetime import datetime, timezone

from fastapi import BackgroundTasks, FastAPI, HTTPException
from pydantic import BaseModel

from app.models import ChannelStatus, PostStatus
from app.publishers.base import publish_post
from app.repo import posts
from app.utils.logging import get_logger

log = get_logger(__name__)
app = FastAPI(title="trend-news pipeline-api")

JOB_MODULES = {
    "collect": "app.jobs.collect",
    "generate_daily": "app.jobs.generate_daily",
    "generate_weekly": "app.jobs.generate_weekly",
    "generate_monthly": "app.jobs.generate_monthly",
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


def _run_job(module_name: str) -> None:
    started = datetime.now(timezone.utc)
    log.info("manual job start", extra={"fields": {"module": module_name}})
    try:
        importlib.import_module(module_name).main()
    except Exception as exc:
        log.error("manual job failed", extra={"fields": {"module": module_name, "error": str(exc)}})
    finally:
        elapsed = (datetime.now(timezone.utc) - started).total_seconds()
        log.info("manual job end", extra={"fields": {"module": module_name, "seconds": elapsed}})


@app.post("/api/jobs/{name}/run", status_code=202)
def run_job(name: str, background: BackgroundTasks) -> dict:
    module = JOB_MODULES.get(name)
    if module is None:
        raise HTTPException(400, f"unknown job {name}")
    background.add_task(_run_job, module)
    return {"accepted": True, "job": name}
