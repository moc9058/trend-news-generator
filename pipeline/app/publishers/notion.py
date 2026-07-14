"""Notion publisher: markdown → blocks, page creation in the Trend News DB,
chunked appends (100 blocks/request) throttled to ~3 req/s."""

import re
import time

import httpx

from app.config import get_settings
from app.utils.logging import get_logger
from app.utils.retry import api_retry

log = get_logger(__name__)

API = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"
BLOCKS_PER_REQUEST = 100
THROTTLE_S = 0.35
MAX_RICH_TEXT = 2000

_INLINE_RE = re.compile(
    r"(\*\*(?P<bold>.+?)\*\*)|(\*(?P<italic>[^*]+?)\*)|(`(?P<code>[^`]+?)`)"
    r"|(\[(?P<label>[^\]]+)\]\((?P<href>[^)\s]+)\))"
)


def _rich_text(text: str) -> list[dict]:
    """Parse a markdown line's inline formatting into Notion rich_text objects."""
    spans: list[dict] = []
    pos = 0
    for m in _INLINE_RE.finditer(text):
        if m.start() > pos:
            spans.append({"type": "text", "text": {"content": text[pos : m.start()]}})
        if m.group("bold") is not None:
            spans.append({
                "type": "text", "text": {"content": m.group("bold")},
                "annotations": {"bold": True},
            })
        elif m.group("italic") is not None:
            spans.append({
                "type": "text", "text": {"content": m.group("italic")},
                "annotations": {"italic": True},
            })
        elif m.group("code") is not None:
            spans.append({
                "type": "text", "text": {"content": m.group("code")},
                "annotations": {"code": True},
            })
        elif m.group("label") is not None:
            spans.append({
                "type": "text",
                "text": {"content": m.group("label"), "link": {"url": m.group("href")}},
            })
        pos = m.end()
    if pos < len(text):
        spans.append({"type": "text", "text": {"content": text[pos:]}})
    # Notion caps a single text content at 2000 chars
    out = []
    for span in spans:
        content = span["text"]["content"]
        while len(content) > MAX_RICH_TEXT:
            head, content = content[:MAX_RICH_TEXT], content[MAX_RICH_TEXT:]
            chunk = {**span, "text": {**span["text"], "content": head}}
            out.append(chunk)
        span["text"]["content"] = content
        out.append(span)
    return out or [{"type": "text", "text": {"content": ""}}]


def _block(block_type: str, text: str) -> dict:
    return {
        "object": "block",
        "type": block_type,
        block_type: {"rich_text": _rich_text(text)},
    }


def markdown_to_blocks(markdown: str) -> list[dict]:
    blocks: list[dict] = []
    lines = markdown.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if not stripped:
            i += 1
            continue
        if stripped.startswith("```"):
            lang = stripped[3:].strip() or "plain text"
            code_lines = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith("```"):
                code_lines.append(lines[i])
                i += 1
            i += 1  # closing fence
            blocks.append({
                "object": "block", "type": "code",
                "code": {
                    "rich_text": _rich_text("\n".join(code_lines)),
                    "language": lang if lang != "plain text" else "plain text",
                },
            })
            continue
        if stripped in ("---", "***", "___"):
            blocks.append({"object": "block", "type": "divider", "divider": {}})
        elif stripped.startswith("### "):
            blocks.append(_block("heading_3", stripped[4:]))
        elif stripped.startswith("## "):
            blocks.append(_block("heading_2", stripped[3:]))
        elif stripped.startswith("# "):
            blocks.append(_block("heading_1", stripped[2:]))
        elif stripped.startswith("> "):
            blocks.append(_block("quote", stripped[2:]))
        elif stripped.startswith(("- ", "* ")):
            blocks.append(_block("bulleted_list_item", stripped[2:]))
        elif re.match(r"^\d+\.\s", stripped):
            blocks.append(_block("numbered_list_item", re.sub(r"^\d+\.\s", "", stripped)))
        else:
            blocks.append(_block("paragraph", stripped))
        i += 1
    return blocks


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {get_settings().notion_api_key}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }


@api_retry
def _post(client: httpx.Client, path: str, payload: dict) -> dict:
    resp = client.post(f"{API}{path}", headers=_headers(), json=payload)
    resp.raise_for_status()
    return resp.json()


@api_retry
def _patch(client: httpx.Client, path: str, payload: dict) -> dict:
    resp = client.patch(f"{API}{path}", headers=_headers(), json=payload)
    resp.raise_for_status()
    return resp.json()


def archive_page(page_id: str) -> None:
    """Archive (soft-delete) a Notion page — the API's delete operation."""
    with httpx.Client(timeout=30) as client:
        try:
            _patch(client, f"/pages/{page_id}", {"archived": True})
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:  # already gone remotely
                return
            raise
    log.info("notion page archived", extra={"fields": {"pageId": page_id}})


def publish(
    title: str,
    markdown_body: str,
    *,
    category: str,
    post_format: str,
    date_iso: str,
) -> tuple[str, str]:
    """Create a page in the Trend News database; returns (page_id, public_url)."""
    from app.repo import configs

    database_id = configs.notion_database_id()
    if not database_id:
        raise RuntimeError("settings/notion.databaseId is not configured")

    blocks = markdown_to_blocks(markdown_body)
    with httpx.Client(timeout=30) as client:
        page = _post(client, "/pages", {
            "parent": {"database_id": database_id},
            "properties": {
                "Name": {"title": [{"text": {"content": title[:200]}}]},
                "Category": {"select": {"name": category}},
                "Format": {"select": {"name": post_format}},
                "Date": {"date": {"start": date_iso}},
            },
            "children": blocks[:BLOCKS_PER_REQUEST],
        })
        page_id, url = page["id"], page.get("url", "")
        for start in range(BLOCKS_PER_REQUEST, len(blocks), BLOCKS_PER_REQUEST):
            time.sleep(THROTTLE_S)
            _patch(client, f"/blocks/{page_id}/children", {
                "children": blocks[start : start + BLOCKS_PER_REQUEST],
            })
    log.info("notion page created", extra={"fields": {"pageId": page_id}})
    return page_id, url
