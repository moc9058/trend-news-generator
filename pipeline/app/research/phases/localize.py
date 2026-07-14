"""R7L localize — generate ko/en from the FROZEN canonical skeleton (design §4.8).
The localizer only renders the same structure in another language; footnote count,
claim assignments and figures are held identical so R8 can machine-verify that the
three languages did not diverge in content.
"""

from app.config import get_settings
from app.research import llm
from app.research.context import RunContext
from app.research.prompts import LOCALIZE_SYSTEM, LOCALIZE_USER, PROMPT_VERSION
from app.research.schemas import LocalizedReport, Phase


def _skeleton(draft) -> str:
    lines = [f"TITLE: {draft.title}", f"SUMMARY: {draft.summary}",
             f"FOOTNOTES: {len(draft.references)}"]
    for i, s in enumerate(draft.sections):
        lines.append(f"SECTION {i + 1}: {s.heading} | claims={s.claimIds} | "
                     f"footnotes={s.footnotes}\n{s.body}")
    return "\n".join(lines)


def run(ctx: RunContext) -> None:
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
            budget=ctx.budget, run_id=run.id, phase=Phase.R7L.value,
            actor="localizer", prompt_version=PROMPT_VERSION)
        loc.language = lang
        ctx.localized[lang] = loc
