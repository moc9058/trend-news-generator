"""Source-connector contract, shared HTTP base, and registry (design §4.3, §7.1).

A connector answers a StrategyQuery with METADATA-ONLY SourceHits — body fetch is
centralised in R4's fetcher (`research/fetch/fetcher.py`). The one exception is
kokkai, whose API returns full speech text, so it attaches `contentText` and R4
skips the fetch.

Resilience (design §7.1): every outbound GET retries 3× with exponential backoff
(honouring Retry-After via `api_retry`); a connector that fails 5 times in a row
self-disables (circuit breaker) so one flaky upstream cannot stall the run. A
failed search is NON-fatal — it returns `[]` and the gap surfaces in coverage.
"""

from typing import Optional, Protocol, runtime_checkable

import httpx

from app.research.schemas import SourceHit, StrategyQuery
from app.utils.logging import get_logger
from app.utils.retry import api_retry

log = get_logger(__name__)

CIRCUIT_BREAK_THRESHOLD = 5
DEFAULT_TIMEOUT = 20.0
USER_AGENT = "trend-news-research/1.0 (+https://github.com/; research agent)"


@runtime_checkable
class SourceConnector(Protocol):
    name: str

    def search(self, q: StrategyQuery) -> list[SourceHit]:
        ...


class HttpConnector:
    """Base for HTTP connectors: retrying GET + circuit breaker + graceful []."""

    name = "base"

    def __init__(self, client: Optional[httpx.Client] = None):
        self._client = client or httpx.Client(
            timeout=DEFAULT_TIMEOUT, headers={"User-Agent": USER_AGENT},
            follow_redirects=True,
        )
        self._consecutive_failures = 0
        self.disabled = False

    # -- HTTP ----------------------------------------------------------------
    @api_retry
    def _get(self, url: str, **kw) -> httpx.Response:
        resp = self._client.get(url, **kw)
        resp.raise_for_status()
        return resp

    def _get_json(self, url: str, **kw) -> dict:
        # _get already retries; don't re-wrap (would multiply attempts).
        return self._get(url, **kw).json()

    # -- public search -------------------------------------------------------
    def search(self, q: StrategyQuery) -> list[SourceHit]:
        if self.disabled:
            return []
        try:
            hits = self._search(q)
            self._consecutive_failures = 0
            return hits
        except Exception as exc:  # noqa: BLE001 — a connector failure is non-fatal
            self._consecutive_failures += 1
            if self._consecutive_failures >= CIRCUIT_BREAK_THRESHOLD:
                self.disabled = True
                log.warning("connector circuit-broken", extra={"fields": {
                    "connector": self.name, "error": str(exc)}})
            else:
                log.warning("connector search failed", extra={"fields": {
                    "connector": self.name, "error": str(exc)}})
            return []

    def _search(self, q: StrategyQuery) -> list[SourceHit]:  # pragma: no cover
        raise NotImplementedError


# --------------------------------------------------------------------------- #
# Registry                                                                     #
# --------------------------------------------------------------------------- #

def build_registry() -> dict[str, SourceConnector]:
    """Instantiate the v1 connectors. Imported lazily to avoid a heavy import at
    module load and to keep each connector optional."""
    from app.research.sources.academic import AcademicConnector
    from app.research.sources.books import BooksConnector
    from app.research.sources.gov_docs import GovDocsConnector
    from app.research.sources.ieee import IeeeConnector
    from app.research.sources.kokkai import KokkaiConnector
    from app.research.sources.news import NewsConnector
    from app.research.sources.web_grounded import WebGroundedConnector

    connectors: list[SourceConnector] = [
        KokkaiConnector(), AcademicConnector(), GovDocsConnector(), BooksConnector(),
        IeeeConnector(), NewsConnector(), WebGroundedConnector(),
    ]
    return {c.name: c for c in connectors}


def get_connectors(names: list[str], registry: Optional[dict] = None) -> list[SourceConnector]:
    """Resolve a plan's strategy names to live connectors, dropping unknowns."""
    reg = registry if registry is not None else build_registry()
    return [reg[n] for n in names if n in reg]
