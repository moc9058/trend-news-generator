from datetime import datetime, timezone

from google.cloud import firestore

from app.models import ChannelState, Post, PostStatus
from app.repo.client import db

COLLECTION = "posts"


def create(post: Post) -> str:
    post.createdAt = datetime.now(timezone.utc)
    _, ref = db().collection(COLLECTION).add(post.model_dump(exclude={"id"}))
    return ref.id


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
