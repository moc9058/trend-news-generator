"""write — canonical (ja) ReportDraft + localization in one phase (design §4.8).

Writer leg: canonical draft from verified claims. Every assertion cites an
evidenceId; interpretation and contested positions are labelled by the claim's
renderAs. The canonical draft's structured skeleton is what the localizer
copies, so content can't diverge across languages.

Localizer leg: generate the non-canonical languages (ko/en) from the FROZEN
canonical skeleton. The localizer only renders the same structure in another
language; footnote count, claim assignments and figures are held identical so
review can machine-verify that the three languages did not diverge in content.
Running both legs in one phase also guarantees the draft always exists before
localization (the old standalone localize phase silently no-op'd when resumed
without an in-memory draft).
"""

from app.config import get_settings
from app.generators.prompts import custom_instructions_block
from app.models import Format
from app.repo import configs, research as repo
from app.research import llm
from app.research.context import RunContext
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


def run(ctx: RunContext) -> None:
    _write_canonical(ctx)
    _localize(ctx)


# -- writer leg ----------------------------------------------------------------

def _write_canonical(ctx: RunContext) -> None:
    run = ctx.run
    claims = ctx.claims or repo.get_claims(run.id)
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
        budget=ctx.budget, run_id=run.id, phase=Phase.write.value,
        actor="writer", prompt_version=PROMPT_VERSION)
    draft.language = run.canonicalLanguage
    ctx.draft = draft
    ctx.localized[run.canonicalLanguage] = to_localized(draft)


# -- localizer leg ---------------------------------------------------------------

def _skeleton(draft) -> str:
    lines = [f"TITLE: {draft.title}", f"SUMMARY: {draft.summary}",
             f"FOOTNOTES: {len(draft.references)}"]
    for i, s in enumerate(draft.sections):
        lines.append(f"SECTION {i + 1}: {s.heading} | claims={s.claimIds} | "
                     f"footnotes={s.footnotes}\n{s.body}")
    return "\n".join(lines)


def _localize(ctx: RunContext) -> None:
    run = ctx.run
    if ctx.draft is None:
        return
    skeleton = _skeleton(ctx.draft)
    for lang in run.languages:
        if lang == run.canonicalLanguage:
            continue
        loc: LocalizedReport = llm.structured(
            LocalizedReport, get_settings().research_model,
            LOCALIZE_SYSTEM.format(language=lang),
            LOCALIZE_USER.format(skeleton=skeleton, language=lang),
            budget=ctx.budget, run_id=run.id, phase=Phase.write.value,
            actor="localizer", prompt_version=PROMPT_VERSION,
            extra_detail={"language": lang})
        loc.language = lang
        ctx.localized[lang] = loc
