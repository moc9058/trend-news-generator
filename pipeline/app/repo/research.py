"""Firestore access for the Research Agent: researchRuns + its evidence / claims
/ events subcollections, plus the transactional lease (design §4.4, §6.1).

This is the repo's first use of a Firestore transaction. `claim_next()` atomically
takes ownership of a `queued` run — or a `running` run whose lease has gone stale —
so a crashed job can be resumed from its last completed phase without two workers
ever advancing the same run (double-execution guard). The lease predicate
`_claimable()` is pure and unit-tested; the transaction is a thin CAS around it.
"""

import random
from datetime import datetime, timezone
from typing import Optional

from google.cloud import firestore

from app.repo.client import db
from app.research.schemas import (
    AuditEvent,
    Claim,
    EvidenceRecord,
    ResearchRun,
    ResearchRunStatus,
)
from app.research.state import is_stale, is_terminal

COLLECTION = "researchRuns"
_RAND_ALPHABET = "abcdefghijklmnopqrstuvwxyz0123456789"


def new_run_id(now: Optional[datetime] = None, rand: str = "") -> str:
    """`rr_{YYYYMMDD}_{rand6}`. `rand` is injectable for deterministic tests."""
    now = now or datetime.now(timezone.utc)
    suffix = rand or "".join(random.choice(_RAND_ALPHABET) for _ in range(6))
    return f"rr_{now.strftime('%Y%m%d')}_{suffix}"


# --------------------------------------------------------------------------- #
# Run CRUD                                                                     #
# --------------------------------------------------------------------------- #

def create(run: ResearchRun) -> str:
    """Create a queued run keyed by its rr_ id. Returns the id."""
    now = datetime.now(timezone.utc)
    if not run.id:
        run.id = new_run_id(now)
    run.createdAt = run.createdAt or now
    run.updatedAt = now
    db().collection(COLLECTION).document(run.id).create(run.model_dump(exclude={"id"}))
    return run.id


def get(run_id: str) -> Optional[ResearchRun]:
    snap = db().collection(COLLECTION).document(run_id).get()
    if not snap.exists:
        return None
    return ResearchRun(id=snap.id, **snap.to_dict())


def save(run: ResearchRun) -> None:
    """Persist the run's state at a phase boundary (design §3.1 step 1)."""
    run.updatedAt = datetime.now(timezone.utc)
    db().collection(COLLECTION).document(run.id).set(run.model_dump(exclude={"id"}))


def update_fields(run_id: str, fields: dict) -> None:
    fields = {**fields, "updatedAt": datetime.now(timezone.utc)}
    db().collection(COLLECTION).document(run_id).update(fields)


def set_status(run_id: str, status: str, **extra) -> None:
    update_fields(run_id, {"status": status, **extra})


def heartbeat(run_id: str, now: Optional[datetime] = None) -> None:
    """Refresh the lease; called at every phase boundary so a live worker keeps
    ownership and a dead one's run goes stale after LEASE_TTL_MIN."""
    update_fields(run_id, {"heartbeatAt": now or datetime.now(timezone.utc)})


def request_cancel(run_id: str) -> bool:
    """Flag a run for cancellation; the harness honours it at the next phase
    boundary. Returns False if the run is already terminal (API returns 409)."""
    run = get(run_id)
    if run is None or is_terminal(run.status):
        return False
    update_fields(run_id, {"cancelRequested": True})
    return True


# --------------------------------------------------------------------------- #
# Transactional lease (design §6.1)                                            #
# --------------------------------------------------------------------------- #

def _claimable(status: str, heartbeat_at: Optional[datetime],
               now: Optional[datetime] = None) -> bool:
    """PURE lease predicate. A run may be claimed iff it is `queued`, or it is
    `running` but its lease has lapsed (crash → resume). Terminal and freshly
    heart-beating `running` runs are not claimable."""
    if status == ResearchRunStatus.queued.value:
        return True
    if status == ResearchRunStatus.running.value:
        return is_stale(heartbeat_at, now)
    return False


def claim_next(worker_id: str, now: Optional[datetime] = None,
               scan_limit: int = 20) -> Optional[ResearchRun]:
    """Atomically claim the oldest claimable run for `worker_id`. Returns the
    claimed ResearchRun (now `running`, lease held) or None if the queue is empty.

    `worker_id` = CLOUD_RUN_EXECUTION, which is stable across a Cloud Run Job's
    task retries, so the same execution re-acquires its own lease immediately.
    """
    now = now or datetime.now(timezone.utc)
    client = db()
    candidates = (
        client.collection(COLLECTION)
        .where(filter=firestore.FieldFilter(
            "status", "in",
            [ResearchRunStatus.queued.value, ResearchRunStatus.running.value]))
        .order_by("createdAt")
        .limit(scan_limit)
        .get()
    )
    for snap in candidates:
        data = snap.to_dict() or {}
        if not _claimable(data.get("status", ""), data.get("heartbeatAt"), now):
            continue
        claimed = _run_claim_txn(client, snap.reference, worker_id, now)
        if claimed is not None:
            return claimed
    return None


def _run_claim_txn(client, ref, worker_id: str,
                   now: datetime) -> Optional[ResearchRun]:
    transaction = client.transaction()

    @firestore.transactional
    def _txn(txn) -> Optional[ResearchRun]:
        snap = ref.get(transaction=txn)
        if not snap.exists:
            return None
        data = snap.to_dict() or {}
        # Re-check under the transaction: another worker may have taken it.
        if not _claimable(data.get("status", ""), data.get("heartbeatAt"), now):
            return None
        updates = {
            "status": ResearchRunStatus.running.value,
            "claimedBy": worker_id,
            "claimedAt": now,
            "heartbeatAt": now,
            "updatedAt": now,
        }
        txn.update(ref, updates)
        return ResearchRun(id=ref.id, **{**data, **updates})

    return _txn(transaction)


# --------------------------------------------------------------------------- #
# Evidence / claims / events subcollections                                   #
# --------------------------------------------------------------------------- #

def evidence_create_if_absent(run_id: str, ev: EvidenceRecord) -> bool:
    """Create evidence keyed by evidenceId (urlHash). Idempotent — a re-run of a
    phase that re-extracts the same URL does not duplicate (items.py idiom)."""
    ref = (db().collection(COLLECTION).document(run_id)
           .collection("evidence").document(ev.evidenceId))
    try:
        ref.create(ev.model_dump(exclude={"evidenceId"}))
        return True
    except Exception as exc:  # AlreadyExists
        if type(exc).__name__ == "AlreadyExists":
            return False
        raise


def get_evidence(run_id: str) -> list[EvidenceRecord]:
    docs = (db().collection(COLLECTION).document(run_id)
            .collection("evidence").get())
    return [EvidenceRecord(evidenceId=d.id, **d.to_dict()) for d in docs]


def upsert_claim(run_id: str, claim: Claim) -> None:
    (db().collection(COLLECTION).document(run_id)
     .collection("claims").document(claim.claimId)
     .set(claim.model_dump(exclude={"claimId"})))


def get_claims(run_id: str) -> list[Claim]:
    docs = (db().collection(COLLECTION).document(run_id)
            .collection("claims").get())
    return [Claim(claimId=d.id, **d.to_dict()) for d in docs]


def append_event(run_id: str, event: AuditEvent) -> None:
    """Append-only audit log write (never updated/deleted)."""
    (db().collection(COLLECTION).document(run_id)
     .collection("events").add(event.model_dump()))
