"""R3 triage — near-duplicate title dedup (reuses normalize.title_norm_hash), then
an LLM ranks/tiers the candidates. Tertiary hits are dropped (navigation only,
never cited — design §4.2). Selection is capped to keep R4 cost bounded.
"""

from pydantic import BaseModel

from app.config import get_settings
from app.normalize import title_norm_hash
from app.research import llm
from app.research.context import RunContext
from app.research.prompts import PROMPT_VERSION, TRIAGE_SYSTEM, TRIAGE_USER
from app.research.schemas import Phase

MAX_SELECTED = 20


class _Selection(BaseModel):
    index: int
    keep: bool = True
    tier: str = "secondary"
    relevance: float = 0.0
    rationale: str = ""


class TriageOut(BaseModel):
    selections: list[_Selection] = []


def _dedup_titles(hits: list) -> list:
    seen: set[str] = set()
    out = []
    for h in hits:
        k = title_norm_hash(h.title)
        if k in seen:
            continue
        seen.add(k)
        out.append(h)
    return out


def run(ctx: RunContext) -> None:
    candidates = _dedup_titles(ctx.hits)
    if not candidates:
        ctx.selected = []
        return
    rendered = "\n".join(
        f"[{i}] {h.title} | {h.sourceType} | {h.connector} | {h.snippet[:120]}"
        for i, h in enumerate(candidates))
    out: TriageOut = llm.structured(
        TriageOut, get_settings().research_fast_model, TRIAGE_SYSTEM,
        TRIAGE_USER.format(rq=ctx.run.theme, candidates=rendered,
                           n=min(len(candidates), MAX_SELECTED)),
        budget=ctx.budget, run_id=ctx.run.id, phase=Phase.R3.value,
        actor="triage", prompt_version=PROMPT_VERSION)

    kept = []
    for sel in out.selections:
        if 0 <= sel.index < len(candidates) and sel.keep and sel.tier != "tertiary":
            h = candidates[sel.index]
            h.tierHint = sel.tier
            kept.append(h)
    ctx.selected = kept[:MAX_SELECTED] or candidates[:5]
