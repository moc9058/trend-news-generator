"""Thin OpenAI wrapper: JSON-mode chat call + token cost accounting."""

import json
from functools import lru_cache

from openai import OpenAI

from app.config import get_settings
from app.models import TokenUsage
from app.utils import observability

# USD per 1M tokens (input, output) — keep in sync with docs/setup-credentials.md
PRICES = {
    "gpt-5.6-sol": (5.00, 30.00),
    "gpt-5.6-terra": (2.50, 15.00),
    "gpt-5.6-luna": (1.00, 6.00),
    # legacy models — kept so Firestore promptTemplates.modelOverride values
    # that still pin an old model keep pricing correctly.
    "gpt-5.4-mini": (0.75, 4.50),
    "gpt-5.5": (5.00, 30.00),
    # Deep Research assist (research report only; ~$2/call in practice, §4.3).
    "o4-mini-deep-research": (2.00, 8.00),
}


@lru_cache
def _client() -> OpenAI:
    client = OpenAI(api_key=get_settings().openai_api_key)
    ls = observability.ls_client()
    if ls is not None:
        # Patches the instance's methods in place (and returns it) — tracing only.
        # Cost accounting stays ours: PRICES/cost_usd below are unaffected.
        from langsmith.wrappers import wrap_openai

        client = wrap_openai(client, tracing_extra={"client": ls})
    return client


def cost_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    inp, out = PRICES.get(model, (0.0, 0.0))
    return round((input_tokens * inp + output_tokens * out) / 1_000_000, 6)


def generate_json(
    model: str, system_prompt: str, user_prompt: str, usage: TokenUsage
) -> dict:
    """One JSON-mode completion; accumulates tokens/cost into `usage`."""
    resp = _client().chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        response_format={"type": "json_object"},
    )
    if resp.usage:
        usage.inputTokens += resp.usage.prompt_tokens
        usage.outputTokens += resp.usage.completion_tokens
        usage.costUsd = round(
            usage.costUsd + cost_usd(model, resp.usage.prompt_tokens, resp.usage.completion_tokens),
            6,
        )
    return json.loads(resp.choices[0].message.content or "{}")
