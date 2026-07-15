"""LangSmith tracing wiring (observability only — never load-bearing).

Tracing is enabled only when both LANGSMITH_TRACING and LANGSMITH_API_KEY are
set; in production `infra/10-deploy-pipeline.sh` sets both iff the optional
`langsmith-api-key` secret exists, so deleting that secret and redeploying is
the kill switch. Every entry point here swallows its exceptions: a tracing fault
must never fail a run.

Payloads (prompts, generated text, fetched article excerpts) are sent in full to
LangSmith's US SaaS — an accepted, user-approved trade-off (docs/runbook.md).
"""

import os
from functools import lru_cache
from typing import Any

from app.config import get_settings
from app.utils.logging import get_logger

log = get_logger(__name__)


def langsmith_enabled() -> bool:
    s = get_settings()
    return bool(s.langsmith_tracing and s.langsmith_api_key)


def _export_env() -> None:
    """Mirror the resolved settings into os.environ.

    The SDK gates every trace on os.environ (`tracing_is_enabled()`), read at
    call time — it never sees `pipeline/.env`, which pydantic-settings loads into
    Settings only. Without this, local runs configured through .env would wrap the
    client and then silently emit nothing, while Cloud Run (real env vars) traced
    fine — a divergence that hides itself. Writing the resolved values back is a
    no-op when they already came from env (production).
    """
    s = get_settings()
    os.environ["LANGSMITH_TRACING"] = "true"
    os.environ["LANGSMITH_API_KEY"] = s.langsmith_api_key
    if s.langsmith_project:
        os.environ["LANGSMITH_PROJECT"] = s.langsmith_project
    # The SDK memoises env lookups (langsmith.utils.get_env_var is lru_cached), so
    # anything that read the flag before this point pinned a stale "off" that no
    # later assignment can undo. Drop the cache to keep the export order-independent.
    try:
        from langsmith import utils as ls_utils

        ls_utils.get_env_var.cache_clear()
    except Exception:  # noqa: BLE001 — best-effort; a private-ish SDK detail
        pass


@lru_cache
def ls_client() -> Any | None:
    """The shared LangSmith client, or None when tracing is off/unavailable.

    This is the single enable point: callers treat a None return as "tracing off".
    """
    if not langsmith_enabled():
        return None
    try:
        from langsmith import Client

        _export_env()
        s = get_settings()
        return Client(api_key=s.langsmith_api_key)
    except Exception as exc:  # noqa: BLE001 — tracing must not break the caller
        log.warning("langsmith client init failed", extra={"fields": {"error": str(exc)}})
        return None


def flush_langsmith() -> None:
    """Drain pending traces before the process exits.

    Cloud Run Jobs can be reclaimed the moment main() returns, which would drop
    traces still queued in the SDK's background sender.
    """
    if not langsmith_enabled():
        return
    try:
        # LangGraph/LangChain tracers (M1+). Guarded: langchain_core is not a
        # dependency yet, and this must stay a no-op until it is.
        from langchain_core.tracers.langchain import wait_for_all_tracers

        wait_for_all_tracers()
    except ImportError:
        pass
    except Exception as exc:  # noqa: BLE001
        log.warning("wait_for_all_tracers failed", extra={"fields": {"error": str(exc)}})
    try:
        client = ls_client()
        if client is not None:
            client.flush()
    except Exception as exc:  # noqa: BLE001
        log.warning("langsmith flush failed", extra={"fields": {"error": str(exc)}})
