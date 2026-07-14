"""review — critic audit + handoff in one phase (design §4.1, §4.4).

Critic leg: (a) machine checks: citecheck (cited evidence exists) + tri-language
footnote-count consistency; (b) LLM scan for unsupported assertions. The
resulting decision is stored on the context: "revise" sends the harness back to
write once; "proceed" runs the handoff leg below.

Handoff leg (only on "proceed"): create the draft Post(format=report) with
per-language content and the researchRunId back-reference, then move the run to
awaiting_review. Idempotent: if the run already has a postId, do nothing.
Publishing (Notion language pages → X/Threads teasers) happens later, on admin
approval, through the existing publish path.
"""

from pydantic import BaseModel

from app.config import get_settings
from app.models import ChannelState, ChannelStatus, Format, LocalizedContent, Post, PostStatus
from app.repo import posts
from app.repo import research as repo
from app.research import llm, state
from app.research.context import RunContext
from app.research.fetch import citecheck
from app.research.prompts import CRITIC_SYSTEM, CRITIC_USER, PROMPT_VERSION
from app.research.schemas import AuditFinding, Phase, ResearchRunStatus


class CriticOut(BaseModel):
    findings: list[AuditFinding] = []
    passed: bool = True


def _lang_consistent(localized: dict) -> bool:
    return len({r.footnoteCount for r in localized.values()}) <= 1


def run(ctx: RunContext) -> None:
    _critic(ctx)
    ctx.review_decision = (
        state.critic_decision(ctx.audit, ctx.revisions) if ctx.audit else "proceed")
    if ctx.review_decision == "proceed":
        _handoff(ctx)


# -- critic leg ----------------------------------------------------------------

def _critic(ctx: RunContext) -> None:
    run = ctx.run
    evidence = repo.get_evidence(run.id)
    audit = citecheck.verify_quotes(ctx.draft, evidence)
    audit.triLanguageConsistent = _lang_consistent(ctx.localized)

    canon = ctx.localized.get(run.canonicalLanguage)
    body_text = canon.body if canon else ""
    crit: CriticOut = llm.structured(
        CriticOut, get_settings().research_planner_model, CRITIC_SYSTEM,
        CRITIC_USER.format(body=body_text[:12000],
                           evidence_ids=[e.evidenceId for e in evidence]),
        budget=ctx.budget, run_id=run.id, phase=Phase.review.value,
        actor="critic", prompt_version=PROMPT_VERSION)
    audit.findings += crit.findings
    delete_level = [f for f in audit.findings if f.action == "delete"]
    audit.passed = (audit.citeCheckPassRate >= 0.98
                    and audit.triLanguageConsistent
                    and crit.passed and not delete_level)
    ctx.audit = audit


# -- handoff leg -----------------------------------------------------------------

def _handoff(ctx: RunContext) -> None:
    run = ctx.run
    if run.postId:  # idempotent re-run
        ctx.postId = run.postId
        return

    canon = ctx.localized.get(run.canonicalLanguage)
    localizations = {
        lang: LocalizedContent(title=r.title, summary=r.summary, body=r.body)
        for lang, r in ctx.localized.items()
    }
    post = Post(
        format=Format.report,
        categoryId=run.categoryId or "research",
        status=PostStatus.draft,
        title=(canon.title if canon else run.theme),
        summary=(canon.summary if canon else ""),
        body=(canon.body if canon else ""),
        researchRunId=run.id,
        localizations=localizations,
        channels={
            "notion": ChannelState(enabled=True, lang=run.canonicalLanguage,
                                   status=ChannelStatus.pending),
            "x": ChannelState(enabled=True, lang="ja", status=ChannelStatus.pending),
            "threads": ChannelState(enabled=True, lang="ko", status=ChannelStatus.pending),
        },
    )
    post_id = posts.create(post)
    ctx.postId = post_id
    run.postId = post_id
    run.status = ResearchRunStatus.awaiting_review.value
    repo.save(run)
