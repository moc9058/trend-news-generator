"""R9 handoff — create the draft Post(format=report) with per-language content and
the researchRunId back-reference, then move the run to awaiting_review (design
§4.1, §4.4). Idempotent: if the run already has a postId, do nothing. Publishing
(Notion language pages → X/Threads teasers) happens later, on admin approval,
through the existing publish path.
"""

from app.models import ChannelState, ChannelStatus, Format, LocalizedContent, Post, PostStatus
from app.repo import posts
from app.repo import research as repo
from app.research.context import RunContext
from app.research.schemas import ResearchRunStatus


def run(ctx: RunContext) -> None:
    run = ctx.run
    if run.postId:  # idempotent re-run
        ctx.postId = run.postId
        return

    canon = ctx.localized.get(run.canonicalLanguage)
    localizations = {
        lang: LocalizedContent(title=r.title, summary=r.summary, body=r.body)
        for lang, r in ctx.localized.items()
    }
    post = Post(
        format=Format.report,
        categoryId=run.categoryId or "research",
        status=PostStatus.draft,
        title=(canon.title if canon else run.theme),
        summary=(canon.summary if canon else ""),
        body=(canon.body if canon else ""),
        researchRunId=run.id,
        localizations=localizations,
        channels={
            "notion": ChannelState(enabled=True, lang=run.canonicalLanguage,
                                   status=ChannelStatus.pending),
            "x": ChannelState(enabled=True, lang="ja", status=ChannelStatus.pending),
            "threads": ChannelState(enabled=True, lang="ko", status=ChannelStatus.pending),
        },
    )
    post_id = posts.create(post)
    ctx.postId = post_id
    run.postId = post_id
    run.status = ResearchRunStatus.awaiting_review.value
    repo.save(run)
