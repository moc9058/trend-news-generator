"""A Firestore BaseCheckpointSaver (design §6.1).

Storage model: each checkpoint is serialised WHOLE and split into ≤900KB chunks
under the run it belongs to, so a run's checkpoints are removed with the run and
carry the same access rules as its other subcollections.

  researchRuns/{runId}/checkpoints/{checkpointId}              (meta; commit record)
  researchRuns/{runId}/checkpoints/{checkpointId}/checkpoint_chunks/{i}
  researchRuns/{runId}/checkpoint_writes/{ckptId}__{taskId}__{idx}
  researchRuns/{runId}/checkpoint_writes/{doc}/checkpoint_chunks/{i}

Storing the checkpoint as ONE opaque blob is only correct because the graph uses
no DeltaChannel — with one, LangGraph would hand us partial channel updates that
must be applied against a prior checkpoint rather than replacing it. Our reducers
are plain binary functions, which compile to BinaryOperatorAggregate, never
Delta. builder.py asserts this so the invariant cannot rot silently.

Chunking exists because a Firestore document is capped at ~1MiB and research state
is not small: kokkai hits carry full speech text, so a single state can run to
megabytes.

Only the sync surface is implemented. The async methods stay as BaseCheckpointSaver
left them (raising NotImplementedError) because the graph is deliberately sync —
overriding them with sync-over-async would invite a caller to deadlock.
"""

# Annotations are deferred: BaseCheckpointSaver's surface includes a `list` method,
# which shadows the builtin for every annotation evaluated later in the class body
# (`-> list[tuple]` would resolve to the method and raise at import).
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Iterator, Optional, Sequence

from google.cloud import firestore
from langgraph.checkpoint.base import (
    WRITES_IDX_MAP,
    BaseCheckpointSaver,
    ChannelVersions,
    Checkpoint,
    CheckpointMetadata,
    CheckpointTuple,
)
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from pydantic import BaseModel

from app.config import get_settings
from app.repo.client import db
from app.utils.logging import get_logger

log = get_logger(__name__)


def _allowed_types() -> list[type]:
    """Every pydantic model that may appear in a channel.

    JsonPlusSerializer's default is permissive-with-a-warning ("will be blocked in
    a future version"), and the strict path FAILS SILENTLY: an unlisted type comes
    back as a plain dict instead of raising, so a resumed graph would hand `write`
    a dict where it expects a ReportDraft. Declaring the allowlist means the
    behaviour is pinned now instead of changing under us on a minor bump.

    Derived from the module rather than hand-listed: every nested model needs an
    entry (Claim inside claims, RqCoverage inside CoverageReport, ...), and a
    hand-written list would quietly rot the moment a schema gains a field.
    `test_checkpointer_firestore.py` asserts this covers what the graph stores.
    """
    from app.research import schemas

    return [obj for obj in vars(schemas).values()
            if isinstance(obj, type) and issubclass(obj, BaseModel)]

COLLECTION = "researchRuns"
CHECKPOINTS = "checkpoints"
CHECKPOINT_WRITES = "checkpoint_writes"
CHUNKS = "checkpoint_chunks"

# Firestore's hard limit is ~1,048,576 bytes per document; leave room for the
# other fields and Firestore's own overhead.
CHUNK_BYTES = 900_000


def _now() -> datetime:
    return datetime.now(timezone.utc)


class FirestoreCheckpointSaver(BaseCheckpointSaver[int]):
    """Sync-only checkpointer. `get_next_version` is inherited (int, monotonic)."""

    def __init__(self, client: Optional[firestore.Client] = None,
                 ttl_days: Optional[int] = None):
        super().__init__(serde=JsonPlusSerializer(allowed_msgpack_modules=_allowed_types()))
        self._client = client
        self._ttl_days = ttl_days

    # -- plumbing ------------------------------------------------------------
    @property
    def client(self) -> firestore.Client:
        # Lazily resolved so constructing a saver never touches GCP (import time,
        # tests, `default_graph()` at module scope).
        return self._client or db()

    def _expires_at(self) -> datetime:
        days = (self._ttl_days if self._ttl_days is not None
                else get_settings().research_checkpoint_ttl_days)
        return _now() + timedelta(days=days)

    def _run_doc(self, thread_id: str):
        return self.client.collection(COLLECTION).document(thread_id)

    def _ckpts(self, thread_id: str):
        return self._run_doc(thread_id).collection(CHECKPOINTS)

    def _writes(self, thread_id: str):
        return self._run_doc(thread_id).collection(CHECKPOINT_WRITES)

    def _put_chunks(self, parent_ref, blob: bytes) -> int:
        """Write `blob` as ≤CHUNK_BYTES chunks under `parent_ref`. Returns the count."""
        expires_at = self._expires_at()
        count = 0
        for i in range(0, max(len(blob), 1), CHUNK_BYTES):
            part = blob[i:i + CHUNK_BYTES]
            parent_ref.collection(CHUNKS).document(str(count)).set(
                {"i": count, "data": part, "expiresAt": expires_at})
            count += 1
        return count

    def _get_chunks(self, parent_ref, chunk_count: int) -> bytes:
        """Reassemble a blob. Read by index, never by listing: a `stream()` gives
        no order guarantee, and joining chunks out of order corrupts silently."""
        parts: list[bytes] = []
        for i in range(chunk_count):
            snap = parent_ref.collection(CHUNKS).document(str(i)).get()
            if not snap.exists:
                raise ValueError(
                    f"checkpoint chunk {i}/{chunk_count} missing at {parent_ref.path}")
            data = snap.to_dict()["data"]
            parts.append(bytes(data))
        return b"".join(parts)

    # -- BaseCheckpointSaver (sync) ------------------------------------------
    def put(self, config: dict, checkpoint: Checkpoint, metadata: CheckpointMetadata,
            new_versions: ChannelVersions) -> dict:
        thread_id = config["configurable"]["thread_id"]
        checkpoint_id = checkpoint["id"]
        parent_id = config["configurable"].get("checkpoint_id")

        type_tag, blob = self.serde.dumps_typed(checkpoint)
        meta_type, meta_blob = self.serde.dumps_typed(metadata)

        ckpt_ref = self._ckpts(thread_id).document(checkpoint_id)
        chunk_count = self._put_chunks(ckpt_ref, blob)
        # The meta doc is written LAST and is the commit record: get_tuple only
        # ever finds a checkpoint whose chunks are already durable, so a crash
        # mid-write leaves orphan chunks (TTL reaps them) rather than a
        # half-readable checkpoint.
        ckpt_ref.set({
            "threadId": thread_id,
            "checkpointNs": config["configurable"].get("checkpoint_ns", ""),
            "checkpointId": checkpoint_id,
            "parentCheckpointId": parent_id,
            "type": type_tag,
            "chunkCount": chunk_count,
            "metaType": meta_type,
            "metaChunk": meta_blob,          # metadata is tiny; never chunked
            "step": metadata.get("step"),    # denormalised for debugging only
            "createdAt": _now(),
            "expiresAt": self._expires_at(),
        })
        return {"configurable": {"thread_id": thread_id, "checkpoint_ns": "",
                                 "checkpoint_id": checkpoint_id}}

    def put_writes(self, config: dict, writes: Sequence[tuple[str, Any]],
                   task_id: str, task_path: str = "") -> None:
        thread_id = config["configurable"]["thread_id"]
        checkpoint_id = config["configurable"]["checkpoint_id"]
        for i, (channel, value) in enumerate(writes):
            # WRITES_IDX_MAP pins the special channels (__error__, __interrupt__,
            # ...) to fixed negative indices, so a retried task overwrites its own
            # write instead of appending a duplicate.
            idx = WRITES_IDX_MAP.get(channel, i)
            doc_id = f"{checkpoint_id}__{task_id}__{idx}"
            type_tag, blob = self.serde.dumps_typed(value)
            ref = self._writes(thread_id).document(doc_id)
            chunk_count = self._put_chunks(ref, blob)
            ref.set({
                "checkpointId": checkpoint_id, "taskId": task_id,
                "taskPath": task_path, "idx": idx, "channel": channel,
                "type": type_tag, "chunkCount": chunk_count,
                "createdAt": _now(), "expiresAt": self._expires_at(),
            })

    def get_tuple(self, config: dict) -> Optional[CheckpointTuple]:
        thread_id = config["configurable"]["thread_id"]
        checkpoint_id = config["configurable"].get("checkpoint_id")

        if checkpoint_id:
            snap = self._ckpts(thread_id).document(checkpoint_id).get()
            if not snap.exists:
                return None
            doc = snap.to_dict()
        else:
            # uuid6 ids sort lexicographically by time, so "latest" is a plain
            # descending order_by rather than a timestamp comparison.
            docs = list(self._ckpts(thread_id)
                        .order_by("checkpointId", direction=firestore.Query.DESCENDING)
                        .limit(1).stream())
            if not docs:
                return None
            doc = docs[0].to_dict()
            checkpoint_id = doc["checkpointId"]

        return self._tuple_from_doc(thread_id, doc, with_writes=True)

    def list(self, config: Optional[dict], *, filter: Optional[dict] = None,
             before: Optional[dict] = None, limit: Optional[int] = None
             ) -> Iterator[CheckpointTuple]:
        thread_id = (config or {}).get("configurable", {}).get("thread_id")
        if not thread_id:
            return iter(())
        query = self._ckpts(thread_id).order_by(
            "checkpointId", direction=firestore.Query.DESCENDING)
        if before is not None:
            before_id = before["configurable"]["checkpoint_id"]
            query = query.where(filter=firestore.FieldFilter(
                "checkpointId", "<", before_id))
        if limit is not None and filter is None:
            query = query.limit(limit)

        out: list[CheckpointTuple] = []
        for snap in query.stream():
            # pending_writes are attached to the latest checkpoint only (get_tuple);
            # Pregel does not read them from list() results.
            tup = self._tuple_from_doc(thread_id, snap.to_dict(), with_writes=False)
            if filter and not all(tup.metadata.get(k) == v for k, v in filter.items()):
                continue
            out.append(tup)
            if limit is not None and len(out) >= limit:
                break
        return iter(out)

    def delete_thread(self, thread_id: str) -> None:
        """Drop every checkpoint artifact for a run (called once it succeeds)."""
        for snap in list(self._ckpts(thread_id).stream()):
            ref = self._ckpts(thread_id).document(snap.id)
            self._delete_chunks(ref)
            ref.delete()
        for snap in list(self._writes(thread_id).stream()):
            ref = self._writes(thread_id).document(snap.id)
            self._delete_chunks(ref)
            ref.delete()

    # -- helpers -------------------------------------------------------------
    def _delete_chunks(self, parent_ref) -> None:
        for chunk in list(parent_ref.collection(CHUNKS).stream()):
            parent_ref.collection(CHUNKS).document(chunk.id).delete()

    def _tuple_from_doc(self, thread_id: str, doc: dict,
                        with_writes: bool) -> CheckpointTuple:
        checkpoint_id = doc["checkpointId"]
        ckpt_ref = self._ckpts(thread_id).document(checkpoint_id)
        blob = self._get_chunks(ckpt_ref, int(doc.get("chunkCount") or 0))
        checkpoint = self.serde.loads_typed((doc["type"], blob))
        metadata = self.serde.loads_typed((doc["metaType"], bytes(doc["metaChunk"])))

        parent_config = None
        if doc.get("parentCheckpointId"):
            parent_config = {"configurable": {
                "thread_id": thread_id, "checkpoint_ns": "",
                "checkpoint_id": doc["parentCheckpointId"]}}

        return CheckpointTuple(
            config={"configurable": {"thread_id": thread_id, "checkpoint_ns": "",
                                     "checkpoint_id": checkpoint_id}},
            checkpoint=checkpoint,
            metadata=metadata,
            parent_config=parent_config,
            pending_writes=(self._pending_writes(thread_id, checkpoint_id)
                            if with_writes else None),
        )

    def _pending_writes(self, thread_id: str, checkpoint_id: str) -> list[tuple]:
        out: list[tuple] = []
        snaps = list(self._writes(thread_id)
                     .where(filter=firestore.FieldFilter(
                         "checkpointId", "==", checkpoint_id))
                     .stream())
        for snap in snaps:
            doc = snap.to_dict()
            ref = self._writes(thread_id).document(snap.id)
            blob = self._get_chunks(ref, int(doc.get("chunkCount") or 0))
            value = self.serde.loads_typed((doc["type"], blob))
            out.append((doc["taskId"], doc["channel"], value))
        return out
