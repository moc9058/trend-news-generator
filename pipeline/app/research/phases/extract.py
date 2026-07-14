"""extract — for each selected hit: obtain text (kokkai already carries it;
otherwise fetch through the guarded fetcher), snapshot to GCS with sha256, LLM-
extract quotes/claims, score reliability, and store an EvidenceRecord keyed by
urlHash (idempotent). The extract prompt is hardened against injected instructions
in the fetched content (design §6.6); this phase holds no tool permissions beyond
the fetcher it is handed.
"""

from datetime import datetime, timezone

from app.config import get_settings
from app.normalize import canonicalize_url, item_doc_id
from app.repo import research as repo
from app.research import events, llm, rubric
from app.research.context import RunContext
from app.research.fetch import archive, extract_text
from app.research.prompts import EXTRACT_SYSTEM, EXTRACT_USER, PROMPT_VERSION
from app.research.schemas import EvidenceRecord, Extraction, Phase, Retrieval


def run(ctx: RunContext) -> None:
    run = ctx.run
    for hit in ctx.selected:
        if not ctx.budget.can_afford(Phase.extract) or not ctx.budget.fetch_available():
            break
        url_hash = item_doc_id(canonicalize_url(hit.url))
        text, arch = _obtain_text(ctx, hit, url_hash)
        if not text or arch is None:
            continue
        extraction: Extraction = llm.structured(
            Extraction, get_settings().research_fast_model, EXTRACT_SYSTEM,
            EXTRACT_USER.format(rq=run.theme, title=hit.title, text=text[:12000]),
            budget=ctx.budget, run_id=run.id, phase=Phase.extract.value,
            actor="extractor", prompt_version=PROMPT_VERSION)

        tier = rubric.classify_tier(hit.sourceType, hit.tierHint)
        reliability = rubric.score_reliability(
            hit.sourceType, hit.url, corroboration=0, recency_fit=5)
        ev = EvidenceRecord(
            evidenceId=url_hash, runId=run.id,
            rqIds=sorted(ctx.hit_rqs.get(url_hash, set())),
            sourceType=hit.sourceType, tier=tier, title=hit.title, authors=hit.authors,
            venue=hit.venue, publishedAt=hit.publishedAt,
            accessedAt=datetime.now(timezone.utc).isoformat(),
            url=hit.url, identifiers=hit.identifiers, language=run.canonicalLanguage,
            archive=arch, reliability=reliability, extraction=extraction,
            retrieval=Retrieval(connector=hit.connector, query=run.theme,
                                loop=run.loops, deepResearchAssisted=hit.deepResearchAssisted))
        repo.evidence_create_if_absent(run.id, ev)


def _obtain_text(ctx: RunContext, hit, url_hash: str):
    run = ctx.run
    if hit.contentText:  # kokkai etc. — API returned full text, skip fetch (§4.3)
        arch = archive.snapshot(run.id, url_hash, hit.contentText.encode("utf-8"),
                                "text/plain", hit.connector)
        return hit.contentText, arch
    res = ctx.fetcher.fetch(hit.url)
    ctx.budget.note_fetch()
    if res is None:
        events.fetch(run.id, Phase.extract.value, hit.url, ok=False)
        return "", None
    events.fetch(run.id, Phase.extract.value, hit.url, ok=True)
    arch = archive.snapshot(run.id, url_hash, res.data, res.mimeType, "fetcher")
    return extract_text.extract(res.data, res.mimeType), arch
