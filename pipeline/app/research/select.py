"""Auto theme selection for scheduled report runs (design §4.1 R1).

When a run has no theme (the monthly scheduled trigger), R1 calls this first: it
gathers recent items across categories and asks the fast model to propose one
deep-dive theme. Falls back to a category-based theme when there are no items.
"""

from pydantic import BaseModel

from app.config import get_settings
from app.repo import configs, items
from app.research import llm
from app.research.context import RunContext
from app.research.prompts import PROMPT_VERSION, SELECT_SYSTEM, SELECT_USER
from app.research.schemas import Phase


class ThemePick(BaseModel):
    theme: str = ""
    categoryId: str = ""
    rationale: str = ""


def select_theme(ctx: RunContext) -> tuple[str, str]:
    cats = configs.enabled_categories()
    lines: list[str] = []
    for cat in cats:
        for it in items.recent_for_category(cat.slug, 168, limit=10):
            lines.append(f"[{cat.slug}] {it.title}")

    if not lines:  # nothing collected — fall back to a category-based theme
        if cats:
            return f"{cats[0].name}の最新動向の深掘り調査", cats[0].slug
        return "最新動向の深掘り調査", ""

    pick: ThemePick = llm.structured(
        ThemePick, get_settings().research_fast_model, SELECT_SYSTEM,
        SELECT_USER.format(items="\n".join(lines[:60])),
        budget=ctx.budget, run_id=ctx.run.id, phase=Phase.R1.value,
        actor="selector", prompt_version=PROMPT_VERSION)
    theme = pick.theme or lines[0].split("] ", 1)[-1]
    category = pick.categoryId or (cats[0].slug if cats else "")
    return theme, category
