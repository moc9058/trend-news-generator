"""Structured LLM calls for research phases (design §3.2, §6.5, §7.1).

Every phase LLM call goes through `structured()`: the raw JSON is pydantic-
validated into the phase's output schema (one corrective retry on failure), the
cost is charged to the run Budget, and an audit event is written. Phases NEVER
call openai/genai directly — this is the single enforced seam for validation,
cost accounting and auditing.

Research Chat reuses this seam too (`app/chat/graph.py`). Its `run_id` is a
chatThreads id, not a researchRuns id, so it passes `event_sink` to divert the
audit event away from `researchRuns/{id}/events` — see `event_sink` below.
"""

from typing import Callable, Type, TypeVar

from pydantic import BaseModel, ValidationError

from app.generators.openai_client import generate_json
from app.models import TokenUsage
from app.research import events
from app.research.budget import Budget

T = TypeVar("T", bound=BaseModel)


class ResearchLLMError(RuntimeError):
    """Raised when a phase's LLM output fails schema validation even after retry."""


def structured(schema: Type[T], model: str, system: str, user: str, *,
               budget: Budget, run_id: str, phase: str, actor: str,
               prompt_version: str = "", extra_detail: dict | None = None,
               event_sink: Callable[[dict], None] | None = None) -> T:
    """Validate one JSON LLM call into `schema`, charging `budget` and auditing.

    `event_sink`: when None (every research phase), the audit event is appended to
    `researchRuns/{run_id}/events` as always. A caller whose `run_id` is not a
    researchRuns id passes a sink instead, and receives the event as a dict rather
    than having it written to Firestore.
    """
    usage = TokenUsage()
    last_err = ""

    def _audit(ok: bool, error: str | None = None) -> None:
        budget.charge_usd(usage.costUsd)
        if event_sink is not None:
            event_sink({"phase": phase, "actor": actor, "action": "llm_call",
                        "model": model, "tokensIn": usage.inputTokens,
                        "tokensOut": usage.outputTokens, "costUsd": usage.costUsd,
                        "promptVersion": prompt_version, "ok": ok, "error": error})
            return
        events.llm_call(run_id, phase, actor, model, usage.inputTokens,
                        usage.outputTokens, usage.costUsd, prompt_version,
                        ok=ok, error=error, extra_detail=extra_detail)

    for attempt in range(2):  # original + one corrective retry (§7.1)
        prompt = user if attempt == 0 else (
            user + f"\n\nYour previous output failed validation: {last_err}\n"
            "Return ONLY valid JSON matching the requested schema, nothing else.")
        raw = generate_json(model, system, prompt, usage)
        try:
            obj = schema.model_validate(raw)
        except ValidationError as exc:
            last_err = str(exc)[:300]
            continue
        _audit(True)
        return obj

    _audit(False, last_err)
    raise ResearchLLMError(f"{actor} output failed schema validation: {last_err}")
