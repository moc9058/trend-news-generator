"""write — canonical writer, then per-language localize workers (design §4.8, M2).

M2 absorbed phases/write.py. The canonical (ja) draft must exist before any
localization (the localizer copies its frozen skeleton), so write_canonical is a
plain node that then fans out one worker per non-canonical language. The workers
receive the rendered skeleton STRING in their task payload — a Send's arg is the
worker's whole input and is checkpointed, so we ship the ~KB skeleton rather than
the ReportDraft.

write_canonical is the ONLY emitter of phase_start("write"): the admin flow view
derives its revise edge from "write phase_starts − 1" (compatibility contract D).
"""

from langgraph.runtime import Runtime
from langgraph.types import Command, Send

from app.config import get_settings
from app.generators.prompts import custom_instructions_block
from app.models import Format
from app.repo import configs, research as repo
from app.research import events, llm
from app.research.graph.context import ResearchRuntimeContext
from app.research.graph.nodes.common import afford, budget_snapshot
from app.research.graph.state import LocalizeTask, ResearchState
from app.research.prompts import (
    LOCALIZE_SYSTEM,
    LOCALIZE_USER,
    PROMPT_VERSION,
    WRITE_SYSTEM,
    WRITE_USER,
)
from app.research.schemas import LocalizedReport, Phase, ReportDraft


def render_body(draft: ReportDraft) -> str:
    return "\n\n".join(f"## {s.heading}\n\n{s.body}" for s in draft.sections)


def to_localized(draft: ReportDraft) -> LocalizedReport:
    return LocalizedReport(language=draft.language, title=draft.title,
                           summary=draft.summary, body=render_body(draft),
                           footnoteCount=len(draft.references))


def _skeleton(draft: ReportDraft) -> str:
    lines = [f"TITLE: {draft.title}", f"SUMMARY: {draft.summary}",
             f"FOOTNOTES: {len(draft.references)}"]
    for i, s in enumerate(draft.sections):
        lines.append(f"SECTION {i + 1}: {s.heading} | claims={s.claimIds} | "
                     f"footnotes={s.footnotes}\n{s.body}")
    return "\n".join(lines)


# -- canonical writer + dispatch ---------------------------------------------------

def write_canonical(state: ResearchState, runtime: Runtime[ResearchRuntimeContext]) -> Command:
    if not afford(state, runtime.context, Phase.write):
        return Command(goto="budget_stop", update=budget_snapshot(runtime.context))
    run = state["run"]
    events.phase_start(run.id, Phase.write.value)

    claims = state.get("claims") or repo.get_claims(run.id)
    rendered = "\n".join(
        f"{c.claimId} | {c.renderAs} | {c.text} | ev={c.evidenceIds} | stance={c.stance}"
        for c in claims)
    user_prompt = WRITE_USER.format(theme=run.theme, claims=rendered)
    if run.categoryId:
        # Owner's standing requests (dynamic input, like theme/claims — not part
        # of the hashed PROMPT_VERSION layer).
        user_prompt += custom_instructions_block(
            configs.custom_instructions(run.categoryId, Format.report))
    draft: ReportDraft = llm.structured(
        ReportDraft, get_settings().research_model, WRITE_SYSTEM,
        user_prompt,
        budget=runtime.context.budget, run_id=run.id, phase=Phase.write.value,
        actor="writer", prompt_version=PROMPT_VERSION)
    draft.language = run.canonicalLanguage

    update = {"draft": draft,
              "localized": {run.canonicalLanguage: to_localized(draft)},
              **budget_snapshot(runtime.context)}
    skeleton = _skeleton(draft)
    tasks = [Send("localize_lang", LocalizeTask(lang=lang, skeleton=skeleton))
             for lang in run.languages if lang != run.canonicalLanguage]
    if not tasks:
        return Command(goto="localize_join", update=update)
    return Command(goto=tasks, update=update)


# -- worker ---------------------------------------------------------------------

def localize_lang(task: LocalizeTask, runtime: Runtime[ResearchRuntimeContext]) -> dict:
    """Render the frozen canonical skeleton in one language."""
    ctx = runtime.context
    lang = task["lang"]
    loc: LocalizedReport = llm.structured(
        LocalizedReport, get_settings().research_model,
        LOCALIZE_SYSTEM.format(language=lang),
        LOCALIZE_USER.format(skeleton=task["skeleton"], language=lang),
        budget=ctx.budget, run_id=ctx.run_id, phase=Phase.write.value,
        actor="localizer", prompt_version=PROMPT_VERSION,
        extra_detail={"language": lang})
    loc.language = lang
    return {"localized": {lang: loc}, "budget": ctx.budget.snapshot()}


# -- join -------------------------------------------------------------------------

def localize_join(state: ResearchState, runtime: Runtime[ResearchRuntimeContext]) -> dict:
    events.phase_end(state["run"].id, Phase.write.value)
    return budget_snapshot(runtime.context)
