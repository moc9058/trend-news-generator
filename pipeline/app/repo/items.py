from datetime import datetime, timedelta, timezone

from google.cloud import firestore

from app.models import Item
from app.repo.client import db

COLLECTION = "items"


def create_if_absent(item: Item) -> bool:
    """Transactional create keyed by URL hash; returns False if it already exists."""
    ref = db().collection(COLLECTION).document(item.id)
    try:
        ref.create(item.model_dump(exclude={"id"}))
        return True
    except Exception as exc:  # AlreadyExists
        if type(exc).__name__ == "AlreadyExists":
            return False
        raise


def title_hash_seen_since(category_id: str, title_hash: str, days: int = 7) -> bool:
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    docs = (
        db()
        .collection(COLLECTION)
        .where(filter=firestore.FieldFilter("categoryId", "==", category_id))
        .where(filter=firestore.FieldFilter("titleNormHash", "==", title_hash))
        .where(filter=firestore.FieldFilter("collectedAt", ">=", cutoff))
        .limit(1)
        .get()
    )
    return len(list(docs)) > 0


def recent_for_category(category_id: str, hours: int, limit: int = 120) -> list[Item]:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    docs = (
        db()
        .collection(COLLECTION)
        .where(filter=firestore.FieldFilter("categoryId", "==", category_id))
        .where(filter=firestore.FieldFilter("collectedAt", ">=", cutoff))
        .order_by("collectedAt", direction=firestore.Query.DESCENDING)
        .limit(limit)
        .get()
    )
    return [Item(id=d.id, **d.to_dict()) for d in docs]


def get_many(item_ids: list[str]) -> list[Item]:
    refs = [db().collection(COLLECTION).document(i) for i in item_ids]
    return [
        Item(id=snap.id, **snap.to_dict())
        for snap in db().get_all(refs)
        if snap.exists
    ]


def mark_used(item_ids: list[str], post_id: str) -> None:
    batch = db().batch()
    for item_id in item_ids:
        ref = db().collection(COLLECTION).document(item_id)
        batch.update(ref, {"usedInPostIds": firestore.ArrayUnion([post_id])})
    batch.commit()
