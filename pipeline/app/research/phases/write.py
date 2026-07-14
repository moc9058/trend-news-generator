"""R7 write — canonical (ja) ReportDraft from verified claims. Every assertion
cites an evidenceId; interpretation and contested positions are labelled by the
claim's renderAs (design §4.8). The canonical draft's structured skeleton is what
the localizers copy, so content can't diverge across languages.
"""

from app.config import get_settings
from app.repo import research as repo
from app.research import llm
from app.research.context import RunContext
from app.research.prompts import PROMPT_VERSION, WRITE_SYSTEM, WRITE_USER
from app.research.schemas import LocalizedReport, Phase, ReportDraft


def render_body(draft: ReportDraft) -> str:
    return "\n\n".join(f"## {s.heading}\n\n{s.body}" for s in draft.sections)


def to_localized(draft: ReportDraft) -> LocalizedReport:
    return LocalizedReport(language=draft.language, title=draft.title,
                           summary=draft.summary, body=render_body(draft),
                           footnoteCount=len(draft.references))


def run(ctx: RunContext) -> None:
    run = ctx.run
    claims = ctx.claims or repo.get_claims(run.id)
    rendered = "\n".join(
        f"{c.claimId} | {c.renderAs} | {c.text} | ev={c.evidenceIds} | stance={c.stance}"
        for c in claims)
    draft: ReportDraft = llm.structured(
        ReportDraft, get_settings().research_model, WRITE_SYSTEM,
        WRITE_USER.format(theme=run.theme, claims=rendered),
        budget=ctx.budget, run_id=run.id, phase=Phase.R7.value,
        actor="writer", prompt_version=PROMPT_VERSION)
    draft.language = run.canonicalLanguage
    ctx.draft = draft
    ctx.localized[run.canonicalLanguage] = to_localized(draft)
