"""Short generation job (08:00 JST): generate one post per category and publish
immediately unless the shortRequireApproval safety valve is on."""

from app.generators import short
from app.models import PostStatus, Run
from app.publishers.base import publish_post
from app.repo import configs, items, posts, runs
from app.utils.logging import get_logger

log = get_logger(__name__)


def main() -> None:
    run_id = runs.start("generate_short")
    run = Run(jobType="generate_short")

    for category in configs.enabled_categories():
        try:
            post = short.generate_for_category(category)
        except Exception as exc:
            run.errors.append(f"generate {category.slug}: {exc}")
            log.error("short generation failed", extra={"fields": {"category": category.slug, "error": str(exc)}})
            continue
        if post is None:
            continue
        post_id = posts.create(post)
        items.mark_used(post.sourceItemIds, post_id)
        run.stats.postsCreated += 1
        run.costUsd = round(run.costUsd + post.tokenUsage.costUsd, 6)

        if post.status != PostStatus.approved:
            log.info("short draft held for approval", extra={"fields": {"post": post_id}})
            continue
        try:
            result = publish_post(post_id)
            if result.status == PostStatus.published:
                run.stats.published += 1
            else:
                run.stats.failed += 1
                run.errors.append(f"publish {post_id}: status={result.status.value}")
        except Exception as exc:
            run.stats.failed += 1
            run.errors.append(f"publish {post_id}: {exc}")

    run.ok = not run.errors
    runs.finish(run_id, run)
    log.info("generate_short finished", extra={"fields": run.stats.model_dump()})


if __name__ == "__main__":
    main()
