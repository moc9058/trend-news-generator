"""Access to categories, sources, promptTemplates, channelConfigs and settings/*."""

from datetime import datetime, timezone

from google.cloud import firestore

from app.models import (
    AppSettings,
    Cadence,
    Category,
    Channel,
    ChannelConfig,
    PromptTemplate,
    Source,
)
from app.repo.client import db


def enabled_categories() -> list[Category]:
    docs = (
        db()
        .collection("categories")
        .where(filter=firestore.FieldFilter("enabled", "==", True))
        .get()
    )
    cats = [Category(slug=d.id, **{k: v for k, v in d.to_dict().items() if k != "slug"}) for d in docs]
    return sorted(cats, key=lambda c: c.sortOrder)


def enabled_sources(category_id: str) -> list[Source]:
    docs = (
        db()
        .collection("sources")
        .where(filter=firestore.FieldFilter("categoryId", "==", category_id))
        .where(filter=firestore.FieldFilter("enabled", "==", True))
        .get()
    )
    return [Source(id=d.id, **d.to_dict()) for d in docs]


def update_source_cache(source_id: str, etag: str, last_modified: str) -> None:
    db().collection("sources").document(source_id).update(
        {
            "etag": etag,
            "lastModified": last_modified,
            "lastFetchedAt": datetime.now(timezone.utc),
        }
    )


def prompt_template(category_id: str, cadence: Cadence) -> PromptTemplate | None:
    snap = db().collection("promptTemplates").document(f"{category_id}_{cadence.value}").get()
    if not snap.exists:
        return None
    tpl = PromptTemplate(id=snap.id, **snap.to_dict())
    return tpl if tpl.enabled else None


def category_focus_keywords(category_id: str) -> list[str]:
    """Union (order-preserving, case-insensitive dedupe) of focusKeywords across
    a category's cadence templates. Collection is per-category and shared across
    cadences, so it steers the web search with every keyword the user set for the
    category — regardless of whether a given cadence template is enabled."""
    ordered: list[str] = []
    lower_seen: set[str] = set()
    for cadence in Cadence:
        snap = (
            db().collection("promptTemplates")
            .document(f"{category_id}_{cadence.value}").get()
        )
        if not snap.exists:
            continue
        for kw in (snap.to_dict() or {}).get("focusKeywords", []) or []:
            k = str(kw).strip()
            if k and k.lower() not in lower_seen:
                lower_seen.add(k.lower())
                ordered.append(k)
    return ordered


def channel_config(category_id: str, cadence: Cadence, channel: Channel) -> ChannelConfig:
    doc_id = f"{category_id}_{cadence.value}_{channel.value}"
    snap = db().collection("channelConfigs").document(doc_id).get()
    if not snap.exists:
        return ChannelConfig(
            id=doc_id, categoryId=category_id, cadence=cadence, channel=channel,
            enabled=False, language="en",
        )
    return ChannelConfig(id=snap.id, **snap.to_dict())


def app_settings() -> AppSettings:
    snap = db().collection("settings").document("app").get()
    if not snap.exists:
        return AppSettings()
    return AppSettings(**snap.to_dict())


def notion_database_id() -> str:
    snap = db().collection("settings").document("notion").get()
    return (snap.to_dict() or {}).get("databaseId", "") if snap.exists else ""


def update_channel_health(fields: dict) -> None:
    db().collection("settings").document("channelHealth").set(fields, merge=True)
