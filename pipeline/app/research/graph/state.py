"""The graph's channel schema — what a checkpoint contains (design §4.1, §6.1).

This is the durable in-flight state. Under the old harness these artifacts lived
only in a RunContext held in memory, which is what made a mid-run crash able to
resume `review` with no draft: citecheck saw zero references, scored a vacuous
1.0, and an empty Post was created. Everything review needs is a channel here, so
a resumed run restarts the failed superstep with its inputs intact.

pydantic models are stored as VALUES (JsonPlusSerializer round-trips pydantic v2),
so channels stay strongly typed. The one concession is `hit_rqs`, whose sets are
kept as sorted lists to serialise; nodes/common.py adapts at the RunContext edge.

Reducers are plain binary functions, which LangGraph compiles to
BinaryOperatorAggregate — deliberately NOT DeltaChannel, whose partial-update
semantics would break the checkpointer's whole-blob storage (see checkpointer.py).
"""

from typing import Annotated, Optional, TypedDict

from app.research.schemas import (
    AuditReport,
    BudgetState,
    Claim,
    CoverageReport,
    LocalizedReport,
    ReportDraft,
    ResearchRun,
    SourceHit,
)


def merge_hits(cur: dict, new: dict) -> dict:
    """urlHash-keyed union, first write wins.

    Two connectors returning the same URL is the normal case, and the first hit
    already carries the retrieval context we want to keep.
    """
    merged = dict(cur or {})
    for url_hash, hit in (new or {}).items():
        merged.setdefault(url_hash, hit)
    return merged


def merge_hit_rqs(cur: dict, new: dict) -> dict:
    """Per-urlHash set-union of RQ ids, kept sorted so it serialises stably."""
    merged = {k: list(v) for k, v in (cur or {}).items()}
    for url_hash, rq_ids in (new or {}).items():
        merged[url_hash] = sorted(set(merged.get(url_hash, [])) | set(rq_ids))
    return merged


def merge_localized(cur: dict, new: dict) -> dict:
    """Language-keyed update — one writer per language, so last write wins."""
    merged = dict(cur or {})
    merged.update(new or {})
    return merged


def merge_budget(cur: Optional[BudgetState], new: Optional[BudgetState]) -> BudgetState:
    """Monotonic merge: spend only ever goes up, caps never move.

    Concurrent writers each snapshot the same live Budget, so `max` is the honest
    reconciliation — taking the last write could lose another node's charge and
    let the run overspend its cap. Also used by runner.py to reconcile a resumed
    checkpoint against the run document, where either side may be the fresher one.
    """
    if cur is None:
        return new
    if new is None:
        return cur
    return BudgetState(
        usdCap=max(cur.usdCap, new.usdCap),
        usdSpent=max(cur.usdSpent, new.usdSpent),
        fetchCap=max(cur.fetchCap, new.fetchCap),
        fetchUsed=max(cur.fetchUsed, new.fetchUsed),
        drCallsUsed=max(cur.drCallsUsed, new.drCallsUsed),
    )


class ResearchState(TypedDict, total=False):
    """Channels of the research graph. `total=False`: nodes return partial dicts."""

    run: ResearchRun                              # LastValue; only barrier nodes write it
    budget: Annotated[BudgetState, merge_budget]
    # gather: retrieval leg -> triage leg
    hit_index: Annotated[dict[str, SourceHit], merge_hits]
    hit_rqs: Annotated[dict[str, list[str]], merge_hit_rqs]
    selected: list[SourceHit]                     # LastValue; triage's verdict
    # verify -> write
    claims: list[Claim]
    coverage: Optional[CoverageReport]
    # write -> review
    draft: Optional[ReportDraft]
    localized: Annotated[dict[str, LocalizedReport], merge_localized]
    # review
    audit: Optional[AuditReport]
    review_decision: str                          # "revise" | "proceed"
    revisions: int                                # survives a crash, unlike the old ctx
    post_id: str
    stop_reason: str                              # "" | "budget_exhausted"
