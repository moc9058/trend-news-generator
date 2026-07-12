from datetime import datetime, timedelta, timezone

from google.cloud import firestore

from app.models import ChannelState, Post, PostStatus
from app.repo.client import db

COLLECTION = "posts"


def create(post: Post) -> str:
    post.createdAt = datetime.now(timezone.utc)
    _, ref = db().collection(COLLECTION).add(post.model_dump(exclude={"id"}))
    return ref.id


def delete(post_id: str) -> None:
    db().collection(COLLECTION).document(post_id).delete()


def old_drafts(older_than_days: int) -> list[Post]:
    """Drafts whose createdAt is older than the cutoff. Filters status server-side
    (single-field auto-index) and the age in Python — draft volume is small, so no
    composite index is needed."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=older_than_days)
    docs = (
        db()
        .collection(COLLECTION)
        .where(filter=firestore.FieldFilter("status", "==", PostStatus.draft.value))
        .get()
    )
    out: list[Post] = []
    for d in docs:
        p = Post(id=d.id, **d.to_dict())
        created = p.createdAt
        if created is None:
            continue
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        if created < cutoff:
            out.append(p)
    return out


def get(post_id: str) -> Post | None:
    snap = db().collection(COLLECTION).document(post_id).get()
    if not snap.exists:
        return None
    return Post(id=snap.id, **snap.to_dict())


def set_status(post_id: str, status: PostStatus, **extra) -> None:
    updates: dict = {"status": status.value, **extra}
    db().collection(COLLECTION).document(post_id).update(updates)


def update_channel(post_id: str, channel: str, state: ChannelState) -> None:
    db().collection(COLLECTION).document(post_id).update(
        {f"channels.{channel}": state.model_dump()}
    )


def update_fields(post_id: str, fields: dict) -> None:
    db().collection(COLLECTION).document(post_id).update(fields)


def recent_by_cadence(cadence: str, limit: int = 20) -> list[Post]:
    docs = (
        db()
        .collection(COLLECTION)
        .where(filter=firestore.FieldFilter("cadence", "==", cadence))
        .order_by("createdAt", direction=firestore.Query.DESCENDING)
        .limit(limit)
        .get()
    )
    return [Post(id=d.id, **d.to_dict()) for d in docs]
