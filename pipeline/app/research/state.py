"""Deterministic control decisions for the Research Harness (design §3, §4.1).

These are PURE functions — no LLM, no I/O. The harness (P3) calls them to decide
the next phase, whether to loop, and whether a stale run may be resumed. Keeping
control out of the LLM is what makes the state machine reproducible and testable.
"""

from datetime import datetime, timedelta, timezone
from typing import Optional

from app.research.schemas import (
    AuditReport,
    CoverageReport,
    Phase,
    ResearchRunStatus,
    TERMINAL_STATUSES,
)

# Linear phase order (§4.1). Branches (verify→gather loop, review→write revise)
# are decided by gap_decision()/critic_decision() below, not by linear_next().
PHASE_ORDER: list[Phase] = [
    Phase.plan, Phase.gather, Phase.extract,
    Phase.verify, Phase.write, Phase.review,
]

# A run whose heartbeat is older than this is considered stale and re-claimable
# by the next job execution (design §6.1).
LEASE_TTL_MIN = 30


def linear_next(phase: Phase) -> Optional[Phase]:
    """The next phase in the straight-line order, or None after review."""
    i = PHASE_ORDER.index(phase)
    return PHASE_ORDER[i + 1] if i + 1 < len(PHASE_ORDER) else None


def gap_decision(
    coverage: CoverageReport,
    loops: int,
    max_loops: int,
    can_afford_gather: bool,
) -> str:
    """verify branch: 'loop' back to gather only if some RQ is unresolved AND the
    loop ceiling is not reached AND the budget still allows another gather leg.
    Otherwise 'finalize' → write (unresolved RQs are surfaced as open questions,
    never silently dropped; §6.4)."""
    if loops >= max_loops or not can_afford_gather:
        return "finalize"
    if any(not rq.resolved for rq in coverage.rqCoverage):
        return "loop"
    return "finalize"


def critic_decision(audit: AuditReport, revisions: int, max_revisions: int = 1) -> str:
    """review branch: 'revise' back to write at most `max_revisions` times when
    the audit fails; otherwise 'proceed' to handoff."""
    if not audit.passed and revisions < max_revisions:
        return "revise"
    return "proceed"


def is_stale(heartbeat_at: Optional[datetime], now: Optional[datetime] = None,
             ttl_min: int = LEASE_TTL_MIN) -> bool:
    """True if a `running` run's lease has lapsed (no heartbeat within ttl_min),
    so a fresh execution may take it over and resume from its last phase."""
    now = now or datetime.now(timezone.utc)
    if heartbeat_at is None:
        return True
    hb = heartbeat_at if heartbeat_at.tzinfo else heartbeat_at.replace(tzinfo=timezone.utc)
    return (now - hb) > timedelta(minutes=ttl_min)


def is_terminal(status: str) -> bool:
    """A terminal run is never claimed or resumed."""
    try:
        return ResearchRunStatus(status) in TERMINAL_STATUSES
    except ValueError:
        return False
