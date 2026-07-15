"""Streaming LLM calls for chat, with the same budget/audit discipline that
`research/llm.py: structured()` gives the non-streaming path (design doc 11 §5.3).

This lives here rather than in `research/llm.py` on purpose: that module is the
Research Agent's audited seam and the LangGraph migration keeps it untouched, so
chat's streaming needs stay out of it.
"""

from typing import Callable, Optional

from app.chat.prompts import PROMPT_VERSION
from app.generators.openai_client import stream_text
from app.models import TokenUsage
from app.research.budget import Budget


def stream_chat(*, model: str, system: str, messages: list[dict],
                budget: Budget, on_delta: Callable[[str], None],
                actor: str, phase: str,
                events: Optional[list] = None,
                should_stop: Optional[Callable[[], bool]] = None) -> tuple[str, TokenUsage]:
    """Stream one completion, feeding deltas to `on_delta`; return (text, usage).

    Cost is charged once at the end, because OpenAI reports usage only in a final
    chunk after the content.

    `should_stop` (cancel) stops feeding `on_delta` but deliberately keeps
    draining the stream. Cancelling does not stop the completion being generated
    upstream — we are billed for all of it either way — so abandoning the
    iterator early would only lose the usage chunk and record the message as
    free, silently under-counting the budget. The user sees the stream stop
    immediately regardless; the drain finishes on the worker thread.
    """
    usage = TokenUsage()
    parts: list[str] = []
    stopped = False
    for delta in stream_text(model, system, messages, usage):
        if not stopped:
            parts.append(delta)
            on_delta(delta)
            stopped = should_stop is not None and should_stop()

    budget.charge_usd(usage.costUsd)
    if events is not None:
        events.append({"phase": phase, "actor": actor, "action": "llm_stream",
                       "model": model, "tokensIn": usage.inputTokens,
                       "tokensOut": usage.outputTokens, "costUsd": usage.costUsd,
                       "promptVersion": PROMPT_VERSION, "ok": True, "error": None})
    return "".join(parts), usage
