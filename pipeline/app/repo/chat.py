"""Firestore access for Research Chat: chatThreads + its messages subcollection,
plus the monthly chatUsage rollup (design doc 11 §5.5).

Firestore is the single source of truth for conversation state — the graph holds
no memory between messages and the admin UI reads these documents directly. Two
transactions guard the shared counters: `append_message` allocates `seq` off
`totals.messages`, and `add_usage` accumulates cost. Neither is a lease; unlike
researchRuns there is only ever one writer per thread (one user, one stream).
"""

import random
from datetime import datetime, timezone
from typing import Optional

from google.cloud import firestore

from app.chat.schemas import (
    ChatMessage,
    ChatMessageStatus,
    ChatThread,
    ChatThreadStatus,
)
from app.repo.client import db

COLLECTION = "chatThreads"
MESSAGES = "messages"
USAGE_COLLECTION = "chatUsage"
_RAND_ALPHABET = "abcdefghijklmnopqrstuvwxyz0123456789"


def new_thread_id(now: Optional[datetime] = None, rand: str = "") -> str:
    """`ct_{YYYYMMDD}_{rand6}` (repo/research.py new_run_id style). `rand` is
    injectable for deterministic tests."""
    now = now or datetime.now(timezone.utc)
    suffix = rand or "".join(random.choice(_RAND_ALPHABET) for _ in range(6))
    return f"ct_{now.strftime('%Y%m%d')}_{suffix}"


# --------------------------------------------------------------------------- #
# Threads                                                                      #
# --------------------------------------------------------------------------- #

def create_thread(thread: ChatThread) -> str:
    now = datetime.now(timezone.utc)
    if not thread.id:
        thread.id = new_thread_id(now)
    thread.createdAt = thread.createdAt or now
    thread.updatedAt = now
    db().collection(COLLECTION).document(thread.id).create(
        thread.model_dump(exclude={"id"}))
    return thread.id


def get_thread(thread_id: str) -> Optional[ChatThread]:
    snap = db().collection(COLLECTION).document(thread_id).get()
    if not snap.exists:
        return None
    return ChatThread(id=snap.id, **snap.to_dict())


def update_thread(thread_id: str, fields: dict) -> None:
    fields = {**fields, "updatedAt": datetime.now(timezone.utc)}
    db().collection(COLLECTION).document(thread_id).update(fields)


def request_cancel(thread_id: str) -> bool:
    """Flag the in-flight message for cancellation; the graph honours it at the
    next node boundary. False when the thread does not exist."""
    if get_thread(thread_id) is None:
        return False
    update_thread(thread_id, {"cancelRequested": True})
    return True


def clear_cancel(thread_id: str) -> None:
    update_thread(thread_id, {"cancelRequested": False})


def is_cancelled(thread_id: str) -> bool:
    """Re-read the flag mid-run. Deliberately uncached: this is the only way an
    in-flight graph learns the user pressed cancel."""
    snap = db().collection(COLLECTION).document(thread_id).get()
    return bool(snap.exists and (snap.to_dict() or {}).get("cancelRequested"))


def list_threads(limit: int = 30) -> list[ChatThread]:
    docs = (db().collection(COLLECTION)
            .where(filter=firestore.FieldFilter(
                "status", "==", ChatThreadStatus.active.value))
            .order_by("lastMessageAt", direction=firestore.Query.DESCENDING)
            .limit(limit).get())
    return [ChatThread(id=d.id, **d.to_dict()) for d in docs]


# --------------------------------------------------------------------------- #
# Messages                                                                     #
# --------------------------------------------------------------------------- #

def append_message(thread_id: str, message: ChatMessage) -> str:
    """Append a message, allocating `seq` from the thread's counter atomically.

    seq — not createdAt — is the display order: a user message and its assistant
    reply can land in the same clock tick, and the assistant document is created
    before its text exists.
    """
    client = db()
    thread_ref = client.collection(COLLECTION).document(thread_id)
    msg_ref = thread_ref.collection(MESSAGES).document()
    now = datetime.now(timezone.utc)
    message.createdAt = message.createdAt or now
    transaction = client.transaction()

    @firestore.transactional
    def _txn(txn) -> str:
        snap = thread_ref.get(transaction=txn)
        if not snap.exists:
            raise ValueError(f"chat thread {thread_id} not found")
        data = snap.to_dict() or {}
        seq = int((data.get("totals") or {}).get("messages", 0))
        message.seq = seq
        txn.set(msg_ref, message.model_dump(exclude={"id"}))
        txn.update(thread_ref, {
            "totals.messages": seq + 1,
            "lastMessageAt": now,
            "updatedAt": now,
        })
        return msg_ref.id

    return _txn(transaction)


def get_message(thread_id: str, message_id: str) -> Optional[ChatMessage]:
    snap = (db().collection(COLLECTION).document(thread_id)
            .collection(MESSAGES).document(message_id).get())
    if not snap.exists:
        return None
    return ChatMessage(id=snap.id, **snap.to_dict())


def update_message(thread_id: str, message_id: str, fields: dict) -> None:
    (db().collection(COLLECTION).document(thread_id)
     .collection(MESSAGES).document(message_id).update(fields))


def list_messages(thread_id: str, limit: int = 100) -> list[ChatMessage]:
    docs = (db().collection(COLLECTION).document(thread_id)
            .collection(MESSAGES).order_by("seq").limit(limit).get())
    return [ChatMessage(id=d.id, **d.to_dict()) for d in docs]


def recent_history(thread_id: str, limit: int) -> list[dict]:
    """The last `limit` complete messages as [{role, content}], oldest first.

    Queries seq DESCENDING and reverses, rather than reusing `list_messages`:
    that one limits an ascending query, which would pin a long thread to its
    oldest messages and silently freeze the model's view of the conversation.

    Over-fetches so that dropping unusable messages still leaves a full window.
    Streaming/errored/cancelled messages are excluded — a half-written or failed
    answer is not conversation the model should build on.
    """
    docs = (db().collection(COLLECTION).document(thread_id)
            .collection(MESSAGES)
            .order_by("seq", direction=firestore.Query.DESCENDING)
            .limit(limit * 2).get())
    msgs = [ChatMessage(id=d.id, **d.to_dict()) for d in docs]
    msgs.reverse()
    usable = [m for m in msgs if m.status == ChatMessageStatus.complete.value and m.content]
    return [{"role": m.role, "content": m.content} for m in usable[-limit:]]


def finish_message(thread_id: str, message_id: str, *, content: str, status: str,
                   sources: Optional[list] = None, usage: Optional[dict] = None,
                   error: str = "") -> None:
    """Terminal write for an assistant message (done / error / cancelled)."""
    update_message(thread_id, message_id, {
        "content": content,
        "status": status,
        "sources": [s.model_dump() if hasattr(s, "model_dump") else s
                    for s in (sources or [])],
        "usage": usage,
        "error": error,
    })


def append_handoff(thread_id: str, message_id: str, handoff) -> None:
    """Back-reference from a chat message to what it produced (§5.4)."""
    payload = handoff.model_dump() if hasattr(handoff, "model_dump") else handoff
    (db().collection(COLLECTION).document(thread_id)
     .collection(MESSAGES).document(message_id)
     .update({"handoffs": firestore.ArrayUnion([payload])}))


# --------------------------------------------------------------------------- #
# Usage rollup                                                                 #
# --------------------------------------------------------------------------- #

def add_usage(cost_usd: float, month: str = "", messages: int = 1) -> None:
    """Accumulate one message's cost into chatUsage/{YYYY-MM}.

    The month key is UTC to match getCostSummary()'s existing month boundary in
    the admin dashboard (which is UTC, up to 9h off JST — a known, documented
    wrinkle, not one this introduces).
    """
    month = month or datetime.now(timezone.utc).strftime("%Y-%m")
    ref = db().collection(USAGE_COLLECTION).document(month)
    ref.set({
        "costUsd": firestore.Increment(round(cost_usd, 6)),
        "messages": firestore.Increment(messages),
    }, merge=True)


def add_thread_cost(thread_id: str, cost_usd: float) -> None:
    db().collection(COLLECTION).document(thread_id).update({
        "totals.costUsd": firestore.Increment(round(cost_usd, 6)),
        "updatedAt": datetime.now(timezone.utc),
    })
