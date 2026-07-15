"""Access to categories, sources, promptTemplates, channelConfigs and settings/*."""

from datetime import datetime, timezone

from google.cloud import firestore

from app.models import (
    AppSettings,
    Category,
    Channel,
    ChannelConfig,
    Format,
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


def category(slug: str) -> Category | None:
    """One category by slug, enabled or not.

    Unlike `enabled_categories()` this does not filter on `enabled`: a chat
    handoff names its category explicitly, and refusing it because the scheduled
    run is switched off would be surprising.
    """
    if not slug:
        return None
    snap = db().collection("categories").document(slug).get()
    if not snap.exists:
        return None
    data = snap.to_dict() or {}
    return Category(slug=snap.id, **{k: v for k, v in data.items() if k != "slug"})


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


def prompt_template(category_id: str, post_format: Format) -> PromptTemplate | None:
    snap = db().collection("promptTemplates").document(f"{category_id}_{post_format.value}").get()
    if not snap.exists:
        return None
    tpl = PromptTemplate(id=snap.id, **snap.to_dict())
    return tpl if tpl.enabled else None


def category_focus_keywords(category_id: str) -> list[str]:
    """Union (order-preserving, case-insensitive dedupe) of focusKeywords across
    a category's format templates. Collection is per-category and shared across
    formats, so it steers the web search with every keyword the user set for the
    category — regardless of whether a given format template is enabled."""
    ordered: list[str] = []
    lower_seen: set[str] = set()
    for post_format in Format:
        snap = (
            db().collection("promptTemplates")
            .document(f"{category_id}_{post_format.value}").get()
        )
        if not snap.exists:
            continue
        for kw in (snap.to_dict() or {}).get("focusKeywords", []) or []:
            k = str(kw).strip()
            if k and k.lower() not in lower_seen:
                lower_seen.add(k.lower())
                ordered.append(k)
    return ordered


def channel_config(category_id: str, post_format: Format, channel: Channel) -> ChannelConfig:
    """Per-category config ANDed with the global channel switch in settings/app,
    so turning a channel off in the admin settings silences it everywhere."""
    doc_id = f"{category_id}_{post_format.value}_{channel.value}"
    snap = db().collection("channelConfigs").document(doc_id).get()
    if not snap.exists:
        cfg = ChannelConfig(
            id=doc_id, categoryId=category_id, format=post_format, channel=channel,
            enabled=False, language="en",
        )
    else:
        cfg = ChannelConfig(id=snap.id, **snap.to_dict())
    if cfg.enabled and not app_settings().globalChannels.get(channel.value, True):
        cfg.enabled = False
    return cfg


def custom_instructions(category_id: str, post_format: Format) -> str:
    """Owner's standing requests for a category x format. Read raw (ignores the
    template's enabled flag) — preferences apply to manual runs too."""
    snap = db().collection("promptTemplates").document(f"{category_id}_{post_format.value}").get()
    if not snap.exists:
        return ""
    return str((snap.to_dict() or {}).get("customInstructions", "") or "")


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
