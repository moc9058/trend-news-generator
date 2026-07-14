"""Structured LLM calls for research phases (design §3.2, §6.5, §7.1).

Every phase LLM call goes through `structured()`: the raw JSON is pydantic-
validated into the phase's output schema (one corrective retry on failure), the
cost is charged to the run Budget, and an audit event is written. Phases NEVER
call openai/genai directly — this is the single enforced seam for validation,
cost accounting and auditing.
"""

from typing import Type, TypeVar

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
               prompt_version: str = "") -> T:
    usage = TokenUsage()
    last_err = ""
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
        budget.charge_usd(usage.costUsd)
        events.llm_call(run_id, phase, actor, model, usage.inputTokens,
                        usage.outputTokens, usage.costUsd, prompt_version)
        return obj

    budget.charge_usd(usage.costUsd)
    events.llm_call(run_id, phase, actor, model, usage.inputTokens,
                    usage.outputTokens, usage.costUsd, prompt_version,
                    ok=False, error=last_err)
    raise ResearchLLMError(f"{actor} output failed schema validation: {last_err}")
