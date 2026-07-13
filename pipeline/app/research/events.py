"""Append-only audit log for a research run (design §6.5).

Every tool call and LLM call is recorded as an immutable event in
researchRuns/{runId}/events and mirrored to Cloud Logging with the runId, so a
run is fully reconstructable after the fact (reproducibility requirement §8.1).
"""

from datetime import datetime, timezone

from app.repo import research as research_repo
from app.research.schemas import AuditEvent
from app.utils.logging import get_logger

log = get_logger(__name__)


def emit(run_id: str, event: AuditEvent) -> None:
    """Persist one audit event (append-only) and mirror it to structured logs."""
    if event.ts is None:
        event.ts = datetime.now(timezone.utc)
    research_repo.append_event(run_id, event)
    log.info("research_event", extra={"fields": {
        "runId": run_id, "phase": event.phase, "actor": event.actor,
        "action": event.action, "target": event.target[:200], "model": event.model,
        "tokensIn": event.tokensIn, "tokensOut": event.tokensOut,
        "costUsd": event.costUsd, "ok": event.ok, "error": event.error,
        "durationMs": event.durationMs,
    }})


def phase_start(run_id: str, phase: str, actor: str = "harness") -> None:
    emit(run_id, AuditEvent(phase=phase, actor=actor, action="phase_start"))


def phase_end(run_id: str, phase: str, actor: str = "harness", duration_ms: int = 0) -> None:
    emit(run_id, AuditEvent(phase=phase, actor=actor, action="phase_end", durationMs=duration_ms))


def llm_call(run_id: str, phase: str, actor: str, model: str,
             tokens_in: int, tokens_out: int, cost_usd: float,
             prompt_version: str = "", ok: bool = True, error: str | None = None) -> None:
    emit(run_id, AuditEvent(
        phase=phase, actor=actor, action="llm_call", model=model,
        tokensIn=tokens_in, tokensOut=tokens_out, costUsd=cost_usd,
        ok=ok, error=error, detail={"promptVersion": prompt_version} if prompt_version else {},
    ))


def fetch(run_id: str, phase: str, url: str, ok: bool,
          duration_ms: int = 0, error: str | None = None) -> None:
    emit(run_id, AuditEvent(phase=phase, actor="fetcher", action="fetch",
                            target=url, ok=ok, durationMs=duration_ms, error=error))


def connector_search(run_id: str, phase: str, connector: str, query: str,
                     hits: int, ok: bool = True, error: str | None = None) -> None:
    emit(run_id, AuditEvent(phase=phase, actor=connector, action="connector_search",
                            target=query, ok=ok, error=error, detail={"hits": hits}))


def budget_check(run_id: str, phase: str, remaining: float, ok: bool) -> None:
    emit(run_id, AuditEvent(phase=phase, actor="harness", action="budget_check",
                            ok=ok, detail={"remainingUsd": remaining}))


def fallback(run_id: str, phase: str, actor: str, detail: dict) -> None:
    emit(run_id, AuditEvent(phase=phase, actor=actor, action="fallback", detail=detail))


def circuit_break(run_id: str, phase: str, connector: str, detail: dict) -> None:
    emit(run_id, AuditEvent(phase=phase, actor=connector, action="circuit_break",
                            ok=False, detail=detail))
