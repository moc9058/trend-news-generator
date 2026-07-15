"""extract — dispatch / per-document workers / join (design §4.1, M2 fan-out).

M2 absorbed phases/extract.py and fanned it out per selected document. Workers
share the run's live Budget and the locked Fetcher from the runtime context;
`try_note_fetch()` claims a fetch slot atomically, so the fetch cap holds exactly
even with every worker racing for the last slot. Evidence stays idempotent by
urlHash (`create_if_absent`), so a worker retried after a crash cannot duplicate.
"""

from datetime import datetime, timezone

from langgraph.runtime import Runtime
from langgraph.types import Command, Send

from app.config import get_settings
from app.normalize import canonicalize_url, item_doc_id
from app.repo import research as repo
from app.research import events, llm, rubric
from app.research.fetch import archive, extract_text
from app.research.graph.context import ResearchRuntimeContext
from app.research.graph.nodes.common import afford, budget_snapshot
from app.research.graph.state import RESET, ExtractTask, ResearchState
from app.research.prompts import EXTRACT_SYSTEM, EXTRACT_USER, PROMPT_VERSION
from app.research.schemas import EvidenceRecord, Extraction, Phase, Retrieval


# -- dispatch ------------------------------------------------------------------

def extract_dispatch(state: ResearchState, runtime: Runtime[ResearchRuntimeContext]) -> Command:
    if not afford(state, runtime.context, Phase.extract):
        return Command(goto="budget_stop", update=budget_snapshot(runtime.context))
    run = state["run"]
    events.phase_start(run.id, Phase.extract.value)

    hit_rqs = state.get("hit_rqs") or {}
    tasks = []
    for hit in state.get("selected") or []:
        url_hash = item_doc_id(canonicalize_url(hit.url))
        tasks.append(Send("extract_one", ExtractTask(
            hit=hit, url_hash=url_hash,
            rq_ids=sorted(hit_rqs.get(url_hash, [])), loop=run.loops,
            theme=run.theme or "", language=run.canonicalLanguage)))
    if not tasks:
        return Command(goto="extract_join", update={"evidence_ids": RESET})
    return Command(goto=tasks, update={"evidence_ids": RESET})


# -- worker ---------------------------------------------------------------------

def extract_one(task: ExtractTask, runtime: Runtime[ResearchRuntimeContext]) -> dict:
    """Fetch → snapshot → LLM-extract → EvidenceRecord, for one document."""
    ctx = runtime.context
    if not ctx.budget.can_afford(Phase.extract):
        return {}
    hit, url_hash = task["hit"], task["url_hash"]
    run_id = ctx.run_id

    text, arch = _obtain_text(ctx, hit, url_hash)
    if not text or arch is None:
        return {"budget": ctx.budget.snapshot()}

    extraction: Extraction = llm.structured(
        Extraction, get_settings().research_fast_model, EXTRACT_SYSTEM,
        EXTRACT_USER.format(rq=task["theme"], title=hit.title, text=text[:12000]),
        budget=ctx.budget, run_id=run_id, phase=Phase.extract.value,
        actor="extractor", prompt_version=PROMPT_VERSION)

    tier = rubric.classify_tier(hit.sourceType, hit.tierHint)
    reliability = rubric.score_reliability(
        hit.sourceType, hit.url, corroboration=0, recency_fit=5)
    ev = EvidenceRecord(
        evidenceId=url_hash, runId=run_id,
        rqIds=list(task["rq_ids"]),
        sourceType=hit.sourceType, tier=tier, title=hit.title, authors=hit.authors,
        venue=hit.venue, publishedAt=hit.publishedAt,
        accessedAt=datetime.now(timezone.utc).isoformat(),
        url=hit.url, identifiers=hit.identifiers, language=task["language"],
        archive=arch, reliability=reliability, extraction=extraction,
        retrieval=Retrieval(connector=hit.connector, query=task["theme"],
                            loop=task["loop"],
                            deepResearchAssisted=hit.deepResearchAssisted))
    repo.evidence_create_if_absent(run_id, ev)
    return {"evidence_ids": [url_hash], "budget": ctx.budget.snapshot()}


def _obtain_text(ctx: ResearchRuntimeContext, hit, url_hash: str):
    run_id = ctx.run_id
    if hit.contentText:  # kokkai etc. — API returned full text, skip fetch (§4.3)
        arch = archive.snapshot(run_id, url_hash, hit.contentText.encode("utf-8"),
                                "text/plain", hit.connector)
        return hit.contentText, arch
    # Claim the slot atomically BEFORE fetching; it is consumed even if the fetch
    # fails, exactly as the sequential code counted every attempt.
    if not ctx.budget.try_note_fetch():
        return "", None
    res = ctx.fetcher.fetch(hit.url)
    if res is None:
        events.fetch(run_id, Phase.extract.value, hit.url, ok=False)
        return "", None
    events.fetch(run_id, Phase.extract.value, hit.url, ok=True)
    arch = archive.snapshot(run_id, url_hash, res.data, res.mimeType, "fetcher")
    return extract_text.extract(res.data, res.mimeType), arch


# -- join -------------------------------------------------------------------------

def extract_join(state: ResearchState, runtime: Runtime[ResearchRuntimeContext]) -> dict:
    events.phase_end(state["run"].id, Phase.extract.value)
    return budget_snapshot(runtime.context)
