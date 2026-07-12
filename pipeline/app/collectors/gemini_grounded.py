"""Gemini + Grounding with Google Search collector.

One grounded prompt per source (a source of type gemini_grounded carries a
query). Gemini returns structured JSON; grounding citation URIs are attached so
provenance survives into Firestore.
"""

import json
import re

from google import genai
from google.genai import types

from app.collectors.base import RawItem
from app.config import get_settings
from app.models import Source
from app.utils.logging import get_logger

log = get_logger(__name__)

_PROMPT = """Search the web for the most significant news from the last 24-48 hours about:
{query}

Return ONLY a JSON array (no prose, no markdown fence) of the 5-8 most newsworthy,
distinct stories. Each element:
{{"title": "...", "url": "https://... (the original article URL)",
  "summary": "2-3 sentence factual summary in English",
  "published": "ISO date if known else null"}}

Rules: prefer primary/reputable sources; skip paywalled-only stories when an open
alternative exists; never invent URLs — only use URLs that appear in search results."""


def _extract_json_array(text: str) -> list:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-z]*\n?|```$", "", text, flags=re.MULTILINE).strip()
    start, end = text.find("["), text.rfind("]")
    if start == -1 or end == -1:
        return []
    try:
        parsed = json.loads(text[start : end + 1])
        return parsed if isinstance(parsed, list) else []
    except json.JSONDecodeError:
        return []


class GeminiGroundedCollector:
    def __init__(self, client: genai.Client | None = None):
        self._client = client or genai.Client(api_key=get_settings().gemini_api_key)

    def collect(
        self, source: Source, focus_keywords: list[str] | None = None
    ) -> list[RawItem]:
        query = source.query
        if focus_keywords:
            query += (
                "\n\nGive extra weight to stories about these focus keywords: "
                + ", ".join(focus_keywords)
                + " — but still return the most newsworthy stories in the topic."
            )
        response = self._client.models.generate_content(
            model=get_settings().gemini_model,
            contents=_PROMPT.format(query=query),
            config=types.GenerateContentConfig(
                tools=[types.Tool(google_search=types.GoogleSearch())],
                temperature=0.2,
            ),
        )
        citations = _grounding_uris(response)
        items = []
        for row in _extract_json_array(response.text or ""):
            if not isinstance(row, dict):
                continue
            url = (row.get("url") or "").strip()
            title = (row.get("title") or "").strip()
            if not url.startswith("http") or not title:
                continue
            items.append(
                RawItem(
                    title=title,
                    url=url,
                    summary=(row.get("summary") or "")[:2000],
                    groundingCitations=citations,
                )
            )
        log.info(
            "gemini grounded collect",
            extra={"fields": {"query": source.query, "keywords": focus_keywords or [],
                              "items": len(items)}},
        )
        return items


def _grounding_uris(response) -> list[str]:
    uris = []
    try:
        for cand in response.candidates or []:
            meta = getattr(cand, "grounding_metadata", None)
            for chunk in getattr(meta, "grounding_chunks", None) or []:
                web = getattr(chunk, "web", None)
                if web and getattr(web, "uri", None):
                    uris.append(web.uri)
    except Exception:  # citation extraction is best-effort
        pass
    return uris[:20]
