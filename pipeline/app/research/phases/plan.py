"""R1 plan — theme → ResearchPlan (RQs + per-RQ source strategies), design §4.1/§4.2.

The Source Strategy Matrix maps each theme class to an ordered connector priority
list; the planner's per-RQ strategies are validated/filled against it so a bad LLM
strategy list can't send the run to the wrong sources.
"""

from app.config import get_settings
from app.repo import research as repo
from app.research import llm, select
from app.research.context import RunContext
from app.research.prompts import PLAN_SYSTEM, PLAN_USER, PROMPT_VERSION
from app.research.schemas import Phase, ResearchPlan

# Source Strategy Matrix (design §4.2): theme class → connector priority order.
STRATEGY_MATRIX: dict[str, list[str]] = {
    "politics_history": ["kokkai", "gov_docs", "books", "academic", "news", "web_grounded"],
    "science_tech": ["academic", "ieee", "news", "web_grounded", "books"],
    "economics": ["academic", "gov_docs", "news", "kokkai", "web_grounded", "books"],
    "intl_affairs": ["news", "gov_docs", "academic", "web_grounded", "kokkai", "books"],
    "society_culture": ["news", "web_grounded", "academic", "books", "kokkai", "gov_docs"],
    "law_regulation": ["gov_docs", "kokkai", "academic", "news", "web_grounded", "books"],
}


def run(ctx: RunContext) -> None:
    run = ctx.run
    if not run.theme:  # scheduled run (theme=null) → auto-select first (§4.1)
        run.theme, run.categoryId = select.select_theme(ctx)
    qblock = ("Existing questions to incorporate:\n" + "\n".join(run.questions)
              if run.questions else "")
    plan: ResearchPlan = llm.structured(
        ResearchPlan, get_settings().research_model, PLAN_SYSTEM,
        PLAN_USER.format(theme=run.theme, questions_block=qblock),
        budget=ctx.budget, run_id=run.id, phase=Phase.R1.value,
        actor="planner", prompt_version=PROMPT_VERSION)

    matrix = STRATEGY_MATRIX.get(plan.themeClass, STRATEGY_MATRIX["society_culture"])
    for rq in plan.rqs:
        valid = [s for s in rq.strategies if s in matrix]
        rq.strategies = valid or matrix[:4]
    run.plan = plan
    repo.save(run)
