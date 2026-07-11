from datetime import datetime, timezone

from app.models import Run
from app.repo.client import db

COLLECTION = "runs"


def start(job_type: str) -> str:
    run = Run(jobType=job_type, startedAt=datetime.now(timezone.utc))
    _, ref = db().collection(COLLECTION).add(run.model_dump(exclude={"id"}))
    return ref.id


def finish(run_id: str, run: Run) -> None:
    run.finishedAt = datetime.now(timezone.utc)
    db().collection(COLLECTION).document(run_id).update(
        run.model_dump(exclude={"id", "jobType", "startedAt"})
    )
