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
from app.publishers.base import delete_post_channels, publish_post
from app.repo import posts
from app.repo import research as research_repo
from app.research.schemas import BudgetState, ResearchRun, ResearchRunStatus
from app.utils.logging import get_logger

log = get_logger(__name__)
app = FastAPI(title="trend-news pipeline-api")

JOB_MODULES = {
    "collect": "app.jobs.collect",
    "generate_short": "app.jobs.generate_short",
    "generate_article": "app.jobs.generate_article",
    "generate_report": "app.jobs.generate_report",
    "cleanup_drafts": "app.jobs.cleanup_drafts",
    "refresh_threads_token": "app.jobs.refresh_threads_token",
    "seed": "app.jobs.seed",
}


class PublishRequest(BaseModel):
    approvedBy: str = ""
    channels: list[str] = []  # empty = all enabled channels


class RetryRequest(BaseModel):
    channel: str


class DeleteRequest(BaseModel):
    channels: list[str] = []  # empty = every channel with a remote artifact
    deletePost: bool = False  # also remove the Firestore doc when nothing stays published


class ResearchRunRequest(BaseModel):
    # Every field defaults so Cloud Scheduler's empty `{}` body does not 422 (§4.6).
    theme: str = ""
    questions: list[str] = []
    categoryId: str = ""
    depth: str = "standard"
    budgetUsd: float = 0.0  # 0 → use the configured default; capped at 30
    languages: list[str] = ["ja", "ko", "en"]
    canonicalLanguage: str = "ja"
    planApproval: bool = False
    requestedBy: str = ""
    trigger: str = "manual"


class ApprovePlanRequest(BaseModel):
    approvedBy: str = ""


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


@app.post("/api/posts/{post_id}/delete")
def delete_post(post_id: str, req: DeleteRequest) -> dict:
    """Delete a post's remote artifacts (X / Threads / Notion) — optionally a
    subset of channels — and, with deletePost, the Firestore document itself."""
    try:
        return delete_post_channels(post_id, req.channels or None, req.deletePost)
    except ValueError:
        raise HTTPException(404, "post not found")


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


# --------------------------------------------------------------------------- #
# Research Agent (report) API — design §4.6. Reads stay in admin (Firestore    #
# direct); only these state-changing actions go through pipeline-api.          #
# --------------------------------------------------------------------------- #

@app.post("/api/research/runs", status_code=202)
def create_research_run(req: ResearchRunRequest) -> dict:
    settings = get_settings()
    cap = min(req.budgetUsd, 30.0) if req.budgetUsd > 0 else settings.research_budget_usd_default
    run = ResearchRun(
        trigger=req.trigger, requestedBy=req.requestedBy, categoryId=req.categoryId,
        theme=req.theme, questions=req.questions, depth=req.depth,
        budget=BudgetState(usdCap=cap, fetchCap=settings.research_max_fetches),
        languages=req.languages, canonicalLanguage=req.canonicalLanguage,
        planApproval=req.planApproval, status=ResearchRunStatus.queued.value)
    run_id = research_repo.create(run)
    # Contract 2 (§4.6): return 202 even if the trigger fails — the run stays
    # queued and the next job execution picks it up via claim_next().
    try:
        _trigger_job("generate_report")
    except Exception as exc:  # noqa: BLE001
        log.warning("generate_report trigger failed; run stays queued",
                    extra={"fields": {"run": run_id, "error": str(exc)}})
    return {"runId": run_id, "accepted": True}


@app.post("/api/research/runs/{run_id}/cancel")
def cancel_research_run(run_id: str) -> dict:
    if research_repo.request_cancel(run_id):
        return {"status": "cancel_requested"}
    run = research_repo.get(run_id)
    if run is None:
        raise HTTPException(404, "research run not found")
    raise HTTPException(409, f"research run is {run.status}")


@app.post("/api/research/runs/{run_id}/approve-plan")
def approve_research_plan(run_id: str, req: ApprovePlanRequest) -> dict:
    run = research_repo.get(run_id)
    if run is None:
        raise HTTPException(404, "research run not found")
    if run.status != ResearchRunStatus.awaiting_plan_approval.value:
        raise HTTPException(409, f"research run is {run.status}, not awaiting_plan_approval")
    research_repo.update_fields(run_id, {
        "planApproved": True, "status": ResearchRunStatus.queued.value})
    try:
        _trigger_job("generate_report")
    except Exception as exc:  # noqa: BLE001
        log.warning("generate_report trigger failed after approve; run stays queued",
                    extra={"fields": {"run": run_id, "error": str(exc)}})
    return {"status": "approved", "approvedBy": req.approvedBy}
