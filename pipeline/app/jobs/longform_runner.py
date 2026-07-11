from app.generators import longform
from app.models import Cadence, Run
from app.repo import configs, items, posts, runs
from app.utils.logging import get_logger

log = get_logger(__name__)


def run_longform(cadence: Cadence) -> None:
    job_type = f"generate_{cadence.value}"
    run_id = runs.start(job_type)
    run = Run(jobType=job_type)

    for category in configs.enabled_categories():
        try:
            post = longform.generate_for_category(category, cadence)
        except Exception as exc:
            run.errors.append(f"generate {category.slug}: {exc}")
            log.error("longform generation failed", extra={"fields": {"category": category.slug, "error": str(exc)}})
            continue
        if post is None:
            continue
        post_id = posts.create(post)
        items.mark_used(post.sourceItemIds, post_id)
        run.stats.postsCreated += 1
        run.costUsd = round(run.costUsd + post.tokenUsage.costUsd, 6)
        log.info("draft created", extra={"fields": {"post": post_id, "cadence": cadence.value}})

    run.ok = not run.errors
    runs.finish(run_id, run)
    log.info(f"{job_type} finished", extra={"fields": run.stats.model_dump()})
