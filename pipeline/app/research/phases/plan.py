"""plan — intake + theme → ResearchPlan (RQs + per-RQ source strategies), design §4.1/§4.2.

The Source Strategy Matrix maps each theme class to an ordered connector priority
list; the planner's per-RQ strategies are validated/filled against it so a bad LLM
strategy list can't send the run to the wrong sources.
"""

from app.config import get_settings
from app.repo import research as repo
from app.research import llm, select
from app.research.context import RunContext
from app.research.prompts import PLAN_SYSTEM, PLAN_USER, PROMPT_VERSION, build_seed_block
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
    # trigger="chat": give the planner what the chat already found, as a lead to
    # verify rather than a conclusion to accept (design doc 11 §5.6).
    user_prompt = (PLAN_USER.format(theme=run.theme, questions_block=qblock)
                   + build_seed_block(run.seedContext))
    plan: ResearchPlan = llm.structured(
        ResearchPlan, get_settings().research_planner_model, PLAN_SYSTEM,
        user_prompt,
        budget=ctx.budget, run_id=run.id, phase=Phase.plan.value,
        actor="planner", prompt_version=PROMPT_VERSION)

    matrix = STRATEGY_MATRIX.get(plan.themeClass, STRATEGY_MATRIX["society_culture"])
    for rq in plan.rqs:
        valid = [s for s in rq.strategies if s in matrix]
        rq.strategies = valid or matrix[:4]
    _inject_deep_research(plan)
    run.plan = plan
    repo.save(run)


def _inject_deep_research(plan: ResearchPlan) -> None:
    """Append the one Deep Research assist leg, to the FIRST RQ only (design §4.3).

    Deliberately deterministic rather than a strategy the planner may choose:
    `deep_research` is kept out of STRATEGY_MATRIX (and so out of PLAN_SYSTEM's
    connector list) because it costs ~$2 a call, and code placing it exactly once
    matches the connector's one-shot budget gate better than asking an LLM to
    ration it. Last in the list, on the theme's central question — it is an assist,
    never a primary source. It self-skips when the provider is off or the budget is
    tight, and is absent from the registry entirely unless a Budget was supplied.
    """
    if plan.rqs and "deep_research" not in plan.rqs[0].strategies:
        plan.rqs[0].strategies.append("deep_research")
