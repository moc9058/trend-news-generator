"""Publish orchestration shared by the short-form job and the admin approve/retry
endpoints.

Order is notion → x → threads: long-form teasers need the Notion public URL.
Idempotency: a channel with an externalId (or status published/skipped) is
never re-published, and a persisted Threads containerId is resumed rather than
recreated, so a crashed run can be retried without double-posting.
"""

from datetime import datetime, timezone

from app.models import ChannelStatus, Post, PostStatus
from app.publishers import notion, renderer, threads, x
from app.repo import configs, posts
from app.utils import gcs
from app.utils.logging import get_logger

log = get_logger(__name__)


def _category_name(category_id: str) -> str:
    for cat in configs.enabled_categories():
        if cat.slug == category_id:
            return cat.name
    return category_id


def _publish_notion(post: Post) -> None:
    state = post.channels["notion"]
    body = post.body or post.summary
    page_id, url = notion.publish(
        post.title,
        body,
        category=_category_name(post.categoryId),
        post_format=post.format.value,
        date_iso=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
    )
    state.externalId = page_id
    state.pageId = page_id
    state.url = url
    state.status = ChannelStatus.published


def _load_image(post: Post, state) -> tuple[bytes, str] | None:
    if not state.imageGcsPath or not configs.app_settings().attachImages:
        return None
    try:
        data = gcs.download_bytes(state.imageGcsPath)
        ext = state.imageGcsPath.rsplit(".", 1)[-1]
        return data, f"image/{'jpeg' if ext == 'jpg' else ext}"
    except Exception as exc:
        log.warning("image load failed", extra={"fields": {"path": state.imageGcsPath, "error": str(exc)}})
        return None


def _publish_x(post: Post, notion_url: str) -> None:
    state = post.channels["x"]
    text = state.text
    app = configs.app_settings()
    is_short = post.format.value == "short"
    if notion_url and (not is_short or app.xAllowUrlOnShort):
        text = renderer.append_url(text, notion_url, renderer.fits_x)
    state.externalId = x.publish(
        text,
        thread_parts=state.threadParts or None,
        image=_load_image(post, state),
    )
    state.url = f"https://x.com/i/status/{state.externalId}"
    state.status = ChannelStatus.published


def _publish_threads(post: Post, post_id: str, notion_url: str) -> None:
    state = post.channels["threads"]
    if not state.containerId:
        text = state.text
        if notion_url and post.format.value != "short":
            text = renderer.append_url(text, notion_url, renderer.fits_threads)
        image_url = ""
        if state.imageGcsPath and configs.app_settings().attachImages:
            try:
                image_url = gcs.signed_url(state.imageGcsPath)
            except Exception as exc:
                log.warning("signed url failed", extra={"fields": {"error": str(exc)}})
        state.containerId = threads.create_container(text, image_url)
        posts.update_channel(post_id, "threads", state)  # crash recovery point
    threads.wait_until_ready(state.containerId)
    state.externalId = threads.publish_container(state.containerId)
    state.status = ChannelStatus.published


def delete_post_channels(
    post_id: str, channels: list[str] | None = None, delete_doc: bool = False
) -> dict:
    """Remove the remote artifacts of a post's published channels (X tweet,
    Threads media, Notion page(s) incl. report localizations), mark them
    `deleted`, and optionally delete the Firestore doc once nothing published
    remains. X limitation: only the first tweet of a thread is stored, so reply
    tweets of a split post survive.
    Returns {"channels": {name: "deleted"|error}, "docDeleted": bool}."""
    post = posts.get(post_id)
    if post is None:
        raise ValueError(f"post {post_id} not found")

    targets = channels or [
        name for name, s in post.channels.items()
        if s.externalId or s.pageId or s.status == ChannelStatus.published
    ]
    results: dict[str, str] = {}
    for name in targets:
        state = post.channels.get(name)
        if state is None:
            results[name] = "unknown channel"
            continue
        if not (state.externalId or state.pageId):
            # nothing remote to remove — just make sure it can't publish later
            state.enabled = False
            if state.status == ChannelStatus.pending:
                state.status = ChannelStatus.skipped
            posts.update_channel(post_id, name, state)
            results[name] = "deleted"
            continue
        try:
            if name == "x":
                x.delete(state.externalId)
            elif name == "threads":
                threads.delete(state.externalId)
            else:
                notion.archive_page(state.pageId or state.externalId)
                for loc in post.localizations.values():
                    if loc.notionPageId and loc.notionPageId != state.pageId:
                        notion.archive_page(loc.notionPageId)
            state.status = ChannelStatus.deleted
            state.enabled = False
            state.error = ""
            posts.update_channel(post_id, name, state)
            results[name] = "deleted"
        except Exception as exc:  # noqa: BLE001 — report per channel, keep going
            state.error = str(exc)[:1000]
            posts.update_channel(post_id, name, state)
            results[name] = f"error: {exc}"
            log.error("channel delete failed", extra={"fields": {
                "post": post_id, "channel": name, "error": str(exc)}})

    doc_deleted = False
    still_published = any(
        s.status == ChannelStatus.published for s in post.channels.values()
    )
    if delete_doc and not still_published and all(
        not v.startswith("error") for v in results.values()
    ):
        posts.delete(post_id)
        doc_deleted = True
    return {"channels": results, "docDeleted": doc_deleted}


def publish_post(post_id: str, only_channel: str = "") -> Post:
    """Publish all pending enabled channels of a post (or a single channel on
    retry). Returns the refreshed post."""
    post = posts.get(post_id)
    if post is None:
        raise ValueError(f"post {post_id} not found")
    posts.set_status(post_id, PostStatus.publishing)

    notion_url = post.channels.get("notion").url if "notion" in post.channels else ""
    order = ["notion", "x", "threads"]
    for channel in order:
        if only_channel and channel != only_channel:
            continue
        state = post.channels.get(channel)
        if state is None or not state.enabled:
            continue
        if state.status in (ChannelStatus.published, ChannelStatus.skipped) or state.externalId:
            continue
        try:
            if channel == "notion":
                _publish_notion(post)
                notion_url = post.channels["notion"].url
            elif channel == "x":
                _publish_x(post, notion_url)
            else:
                _publish_threads(post, post_id, notion_url)
            state.error = ""
        except Exception as exc:
            state.status = ChannelStatus.failed
            state.error = str(exc)[:1000]
            log.error(
                "channel publish failed",
                extra={"fields": {"post": post_id, "channel": channel, "error": str(exc)}},
            )
        posts.update_channel(post_id, channel, state)

    active = [s for s in post.channels.values() if s.enabled]
    published = [s for s in active if s.status == ChannelStatus.published]
    failed = [s for s in active if s.status == ChannelStatus.failed]
    if failed and published:
        final = PostStatus.partially_published
    elif failed:
        final = PostStatus.failed
    else:
        final = PostStatus.published
    posts.set_status(
        post_id, final,
        publishedAt=datetime.now(timezone.utc) if published else None,
    )
    post.status = final
    return post
