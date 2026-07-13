"""Cleanup job (daily 04:00 JST): delete drafts left unapproved for too long.

Article/report generation produces drafts (status=draft) that publish only after
manual approval in the admin UI. Drafts nobody approves would otherwise pile up
forever; this job removes any older than DRAFT_TTL_DAYS. Published/approved posts
are never touched (old_drafts filters status=draft).
"""

from app.models import Run
from app.repo import posts, runs
from app.utils.logging import get_logger

log = get_logger(__name__)

DRAFT_TTL_DAYS = 30


def main() -> None:
    run_id = runs.start("cleanup_drafts")
    run = Run(jobType="cleanup_drafts")

    for p in posts.old_drafts(DRAFT_TTL_DAYS):
        try:
            posts.delete(p.id)
            run.stats.deleted += 1
        except Exception as exc:
            run.errors.append(f"delete {p.id}: {exc}")

    run.ok = not run.errors
    runs.finish(run_id, run)
    log.info("cleanup_drafts finished", extra={"fields": {"deleted": run.stats.deleted}})


if __name__ == "__main__":
    main()
