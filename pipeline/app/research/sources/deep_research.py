"""Deep Research connector (design §4.3) — OpenAI Responses API, background mode.

Flag-gated (config.deep_research_provider). It is a single R2 ASSIST leg: its
returned citations become SourceHits (deepResearchAssisted=true) that flow through
the normal R3–R5 verification pipeline — its prose output is NOT used directly, so
an unverifiable claim from it never reaches the report. Auto-skips when the
provider is off, it has already run once, or the budget is tight (< $3, §4.3).
The Gemini provider can be slotted in behind the same interface.
"""

import time

import httpx

from app.config import get_settings
from app.research.budget import Budget
from app.research.schemas import SourceHit, StrategyQuery
from app.utils.logging import get_logger

log = get_logger(__name__)

RESPONSES_URL = "https://api.openai.com/v1/responses"
POLL_INTERVAL_S = 15
POLL_TIMEOUT_S = 1200  # 20-minute hard timeout (§7.1)


def parse_citations(response: dict) -> list[SourceHit]:
    """Extract url_citation annotations from a Responses payload into SourceHits."""
    hits: list[SourceHit] = []
    seen: set[str] = set()
    for item in response.get("output", []) or []:
        for content in item.get("content") or []:
            for ann in content.get("annotations") or []:
                if ann.get("type") != "url_citation":
                    continue
                url = (ann.get("url") or "").strip()
                if url and url not in seen:
                    seen.add(url)
                    hits.append(SourceHit(
                        title=ann.get("title") or url, url=url,
                        sourceType="web", tierHint="secondary",
                        connector="deep_research", deepResearchAssisted=True))
    return hits


class DeepResearchConnector:
    name = "deep_research"

    def __init__(self, client: httpx.Client | None = None, budget: Budget | None = None):
        self._client = client or httpx.Client(timeout=60)
        self._budget = budget
        self.disabled = False

    def search(self, q: StrategyQuery) -> list[SourceHit]:
        settings = get_settings()
        if self.disabled or settings.deep_research_provider == "off":
            return []
        if self._budget is not None and not self._budget.deep_research_allowed():
            log.info("deep research skipped (budget/one-shot)")
            return []
        try:
            response = self._start_and_poll(q.query)
        except Exception as exc:  # noqa: BLE001 — DR is non-fatal (§7.1)
            log.warning("deep research failed (non-fatal)", extra={"fields": {"error": str(exc)}})
            return []
        if self._budget is not None:
            self._budget.note_deep_research()
        return parse_citations(response)

    def _start_and_poll(self, query: str) -> dict:
        headers = {"Authorization": f"Bearer {get_settings().openai_api_key}",
                   "Content-Type": "application/json"}
        start = self._client.post(RESPONSES_URL, headers=headers, json={
            "model": get_settings().deep_research_model, "background": True,
            "tools": [{"type": "web_search_preview"}],
            "input": f"Research and cite authoritative primary/secondary sources on: {query}"})
        start.raise_for_status()
        run_id = start.json()["id"]
        waited = 0
        while waited < POLL_TIMEOUT_S:
            poll = self._client.get(f"{RESPONSES_URL}/{run_id}", headers=headers)
            poll.raise_for_status()
            data = poll.json()
            if data.get("status") in ("completed", "failed", "cancelled", "incomplete"):
                return data
            time.sleep(POLL_INTERVAL_S)
            waited += POLL_INTERVAL_S
        return {}
