"""R8 critic — (a) machine checks: citecheck (cited evidence exists) + tri-language
footnote-count consistency; (b) LLM scan for unsupported assertions. Fails → the
harness sends it back to R7 once (design §4.1). Passing requires citecheck ≥98%,
the three languages consistent, and no delete-level findings.
"""

from pydantic import BaseModel

from app.config import get_settings
from app.repo import research as repo
from app.research import llm
from app.research.context import RunContext
from app.research.fetch import citecheck
from app.research.prompts import CRITIC_SYSTEM, CRITIC_USER, PROMPT_VERSION
from app.research.schemas import AuditFinding, Phase


class CriticOut(BaseModel):
    findings: list[AuditFinding] = []
    passed: bool = True


def _lang_consistent(localized: dict) -> bool:
    return len({r.footnoteCount for r in localized.values()}) <= 1


def run(ctx: RunContext) -> None:
    run = ctx.run
    evidence = repo.get_evidence(run.id)
    audit = citecheck.verify_quotes(ctx.draft, evidence)
    audit.triLanguageConsistent = _lang_consistent(ctx.localized)

    canon = ctx.localized.get(run.canonicalLanguage)
    body_text = canon.body if canon else ""
    crit: CriticOut = llm.structured(
        CriticOut, get_settings().research_model, CRITIC_SYSTEM,
        CRITIC_USER.format(body=body_text[:12000],
                           evidence_ids=[e.evidenceId for e in evidence]),
        budget=ctx.budget, run_id=run.id, phase=Phase.R8.value,
        actor="critic", prompt_version=PROMPT_VERSION)
    audit.findings += crit.findings
    delete_level = [f for f in audit.findings if f.action == "delete"]
    audit.passed = (audit.citeCheckPassRate >= 0.98
                    and audit.triLanguageConsistent
                    and crit.passed and not delete_level)
    ctx.audit = audit
