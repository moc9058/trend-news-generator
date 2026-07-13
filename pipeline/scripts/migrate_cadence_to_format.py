"""One-shot migration: delivery-cadence → deliverable-format (P0).

Renames the old `cadence` enum (daily/weekly/monthly) to `format`
(short/article/report) everywhere it is *persisted*:

  * promptTemplates/{cat}_{cadence}      -> {cat}_{format}   (docID + `cadence` field)
  * channelConfigs/{cat}_{cadence}_{ch}  -> {cat}_{format}_{ch}
  * posts.*                              field `cadence` -> `format` (docID unchanged)
  * settings/app                         dailyRequireApproval -> shortRequireApproval,
                                         xAllowUrlOnDaily     -> xAllowUrlOnShort
  * Notion DB (--notion)                 "Cadence" select    -> "Format", add "Language"

Design & full runbook: docs/tech-report/05-detailed-design/10-research-agent.md §9.2.

Usage (run locally with ADC + .env):

    python scripts/migrate_cadence_to_format.py            # dry-run (default)
    python scripts/migrate_cadence_to_format.py --apply    # apply the migration
    python scripts/migrate_cadence_to_format.py --apply --notion   # + Notion schema
    python scripts/migrate_cadence_to_format.py --rollback --apply # reverse mapping

Idempotent: re-running finds nothing to do (queries key off the source field/ID
token, which no longer matches once migrated). config docs are created key-first
so a partial run can be resumed safely.
"""

from __future__ import annotations

import argparse

import httpx
from google.cloud import firestore

from app.config import get_settings
from app.models import LEGACY_CADENCE_TO_FORMAT
from app.repo.client import db

# cadence -> format (forward) and its inverse (rollback).
FORWARD: dict[str, str] = dict(LEGACY_CADENCE_TO_FORMAT)
BACKWARD: dict[str, str] = {v: k for k, v in FORWARD.items()}

# settings/app key renames, forward direction.
SETTINGS_KEYS_FORWARD = {
    "dailyRequireApproval": "shortRequireApproval",
    "xAllowUrlOnDaily": "xAllowUrlOnShort",
}


# --------------------------------------------------------------------------- #
# Pure docID re-mapping (unit-tested — no Firestore).                          #
# --------------------------------------------------------------------------- #

def remap_prompt_id(doc_id: str, mapping: dict[str, str]) -> str | None:
    """`{cat}_{key}` -> `{cat}_{mapped}`. Split from the END: a category slug may
    itself contain '_', so a left split would corrupt it. Returns None when the
    trailing token is not a known key (unrecognised / already-migrated docs are
    left untouched, which is what makes the migration idempotent)."""
    cat, sep, key = doc_id.rpartition("_")
    if not sep or not cat or key not in mapping:
        return None
    return f"{cat}_{mapping[key]}"


def remap_channel_id(doc_id: str, mapping: dict[str, str]) -> str | None:
    """`{cat}_{key}_{channel}` -> `{cat}_{mapped}_{channel}`. channel and key are
    single tokens; only the category slug may contain '_', so split off the last
    two tokens from the right."""
    parts = doc_id.rsplit("_", 2)
    if len(parts) != 3:
        return None
    cat, key, channel = parts
    if not cat or key not in mapping:
        return None
    return f"{cat}_{mapping[key]}_{channel}"


# --------------------------------------------------------------------------- #
# Firestore migration steps.                                                   #
# --------------------------------------------------------------------------- #

def _migrate_config_collection(
    client: firestore.Client,
    collection: str,
    remap_fn,
    mapping: dict[str, str],
    old_field: str,
    new_field: str,
    dry_run: bool,
) -> int:
    """Config docs (promptTemplates, channelConfigs) whose docID embeds the
    cadence token: create the renamed doc, then delete the old one. The value
    field (`cadence`->`format`) is remapped in the copied payload."""
    changed = 0
    for snap in client.collection(collection).stream():
        new_id = remap_fn(snap.id, mapping)
        if new_id is None or new_id == snap.id:
            continue
        data = dict(snap.to_dict() or {})
        if old_field in data:
            data[new_field] = mapping.get(data[old_field], data[old_field])
            data.pop(old_field, None)
        print(f"  [{collection}] {snap.id} -> {new_id}  ({old_field}->{new_field}={data.get(new_field)!r})")
        changed += 1
        if dry_run:
            continue
        # create-only so a resumed run does not clobber an already-written doc,
        # then remove the stale ID.
        try:
            client.collection(collection).document(new_id).create(data)
        except Exception as exc:  # google.api_core.exceptions.AlreadyExists
            if type(exc).__name__ != "AlreadyExists":
                raise
        client.collection(collection).document(snap.id).delete()
    return changed


def _migrate_posts(
    client: firestore.Client,
    mapping: dict[str, str],
    old_field: str,
    new_field: str,
    dry_run: bool,
) -> int:
    """posts keep their auto-generated docID; only the field is rewritten. Query
    by the source field so re-runs (field already renamed) match nothing."""
    changed = 0
    batch = client.batch()
    pending = 0
    q = client.collection("posts").where(
        filter=firestore.FieldFilter(old_field, "in", list(mapping.keys()))
    )
    for snap in q.stream():
        old_val = (snap.to_dict() or {}).get(old_field)
        new_val = mapping.get(old_val, old_val)
        print(f"  [posts] {snap.id}  {old_field}={old_val!r} -> {new_field}={new_val!r}")
        changed += 1
        if dry_run:
            continue
        batch.update(snap.reference, {new_field: new_val, old_field: firestore.DELETE_FIELD})
        pending += 1
        if pending >= 400:  # Firestore batch limit is 500; stay well under
            batch.commit()
            batch = client.batch()
            pending = 0
    if not dry_run and pending:
        batch.commit()
    return changed


def _migrate_settings(client: firestore.Client, key_map: dict[str, str], dry_run: bool) -> int:
    ref = client.collection("settings").document("app")
    snap = ref.get()
    if not snap.exists:
        return 0
    data = snap.to_dict() or {}
    updates: dict = {}
    for old_key, new_key in key_map.items():
        if old_key in data:
            print(f"  [settings/app] {old_key} -> {new_key} (={data[old_key]!r})")
            updates[new_key] = data[old_key]
            updates[old_key] = firestore.DELETE_FIELD
    if updates and not dry_run:
        ref.update(updates)
    return len(updates) // 2


# --------------------------------------------------------------------------- #
# Notion database schema (optional).                                           #
# --------------------------------------------------------------------------- #

def _migrate_notion(rollback: bool, dry_run: bool) -> None:
    """Rename the Notion DB's select property (Cadence<->Format) and, forward
    only, add a `Language` select. Select option values are created lazily on the
    first page write, so we only declare the properties here."""
    from app.repo import configs

    settings = get_settings()
    database_id = configs.notion_database_id()
    if not database_id or not settings.notion_api_key:
        print("  [notion] skipped — settings/notion.databaseId or NOTION_API_KEY missing")
        return

    old_name, new_name = ("Format", "Cadence") if rollback else ("Cadence", "Format")
    properties: dict = {old_name: {"name": new_name}}
    if not rollback:
        properties["Language"] = {"select": {}}
    print(f"  [notion] rename property {old_name!r} -> {new_name!r}"
          + ("" if rollback else " + add 'Language' select"))
    if dry_run:
        return
    resp = httpx.patch(
        f"https://api.notion.com/v1/databases/{database_id}",
        headers={
            "Authorization": f"Bearer {settings.notion_api_key}",
            "Notion-Version": "2022-06-28",
            "Content-Type": "application/json",
        },
        json={"properties": properties},
        timeout=30,
    )
    resp.raise_for_status()
    print("  [notion] database schema updated")


# --------------------------------------------------------------------------- #

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="write changes (default: dry-run)")
    parser.add_argument("--dry-run", action="store_true", help="explicit no-op alias for the default")
    parser.add_argument("--rollback", action="store_true", help="reverse mapping (format -> cadence)")
    parser.add_argument("--notion", action="store_true", help="also migrate the Notion DB schema")
    args = parser.parse_args()

    dry_run = not args.apply
    rollback = args.rollback
    mapping = BACKWARD if rollback else FORWARD
    settings_keys = (
        {v: k for k, v in SETTINGS_KEYS_FORWARD.items()} if rollback else SETTINGS_KEYS_FORWARD
    )
    # forward: field cadence->format; rollback: format->cadence
    old_field, new_field = ("format", "cadence") if rollback else ("cadence", "format")

    mode = "DRY-RUN" if dry_run else "APPLY"
    direction = "rollback (format->cadence)" if rollback else "forward (cadence->format)"
    print(f"=== migrate_cadence_to_format [{mode}] {direction} ===")

    client = db()
    total = 0
    total += _migrate_config_collection(
        client, "promptTemplates", remap_prompt_id, mapping, old_field, new_field, dry_run)
    total += _migrate_config_collection(
        client, "channelConfigs", remap_channel_id, mapping, old_field, new_field, dry_run)
    total += _migrate_posts(client, mapping, old_field, new_field, dry_run)
    total += _migrate_settings(client, settings_keys, dry_run)
    if args.notion:
        _migrate_notion(rollback, dry_run)

    print(f"=== {mode}: {total} document(s) {'would change' if dry_run else 'changed'} ===")
    if dry_run:
        print("Re-run with --apply to write.")


if __name__ == "__main__":
    main()
