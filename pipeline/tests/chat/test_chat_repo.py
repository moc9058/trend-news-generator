"""repo/chat.py: id shape, seq allocation, history trimming.

The suite has no Firestore fake (every other test monkeypatches repo functions),
so this file carries a minimal one — just enough surface for the two transactions
in repo/chat.py, whose counter arithmetic is worth testing for real.
"""

import itertools

import pytest

import app.repo.chat as chat_repo
from app.chat.schemas import ChatMessage, ChatMessageStatus, ChatThread


# --------------------------------------------------------------------------- #
# Minimal Firestore fake                                                       #
# --------------------------------------------------------------------------- #

class _Doc:
    def __init__(self, store, path):
        self._store, self._path = store, path
        self.id = path.split("/")[-1]

    def get(self, transaction=None):
        return _Snap(self.id, self._store.get(self._path))

    def create(self, data):
        if self._path in self._store:
            raise Exception("AlreadyExists")
        self._store[self._path] = dict(data)

    def set(self, data, merge=False):
        base = dict(self._store.get(self._path, {})) if merge else {}
        for k, v in data.items():
            # Increment resolves against the existing value even on create,
            # which is what Firestore's set(merge=True) does.
            base[k] = v.apply(base.get(k)) if isinstance(v, _Inc) else v
        self._store[self._path] = base

    def update(self, fields):
        cur = self._store.setdefault(self._path, {})
        for key, value in fields.items():
            if isinstance(value, _Inc):
                value = value.apply(_dotted_get(cur, key))
            elif isinstance(value, _ArrayUnion):
                value = (_dotted_get(cur, key) or []) + value.values
            _dotted_set(cur, key, value)

    def delete(self):
        self._store.pop(self._path, None)

    def collection(self, name):
        return _Coll(self._store, f"{self._path}/{name}")


def _dotted_get(doc, key):
    cur = doc
    for part in key.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


def _dotted_set(doc, key, value):
    parts = key.split(".")
    for part in parts[:-1]:
        doc = doc.setdefault(part, {})
    doc[parts[-1]] = value


class _Snap:
    def __init__(self, id_, data):
        self.id, self._data = id_, data
        self.exists = data is not None

    def to_dict(self):
        return dict(self._data) if self._data else None


_auto_ids = itertools.count(1)


class _Coll:
    def __init__(self, store, path):
        self._store, self._path = store, path

    def document(self, doc_id=None):
        # The counter must outlive this _Coll: repo code re-derives the
        # collection on every call, so a per-instance counter would hand out
        # the same auto-id forever.
        if doc_id is None:
            doc_id = f"auto{next(_auto_ids)}"
        return _Doc(self._store, f"{self._path}/{doc_id}")

    # query surface used by list_messages / list_threads
    def where(self, filter=None):
        return _Query(self._store, self._path).where(filter=filter)

    def order_by(self, field, direction=None):
        return _Query(self._store, self._path).order_by(field, direction)

    def limit(self, n):
        return _Query(self._store, self._path).limit(n)


class _Query:
    def __init__(self, store, path):
        self._store, self._path = store, path
        self._order, self._desc, self._limit, self._filters = None, False, None, []

    def where(self, filter=None):
        self._filters.append(filter)
        return self

    def order_by(self, field, direction=None):
        self._order, self._desc = field, direction == "DESCENDING"
        return self

    def limit(self, n):
        self._limit = n
        return self

    def get(self):
        rows = [(k, v) for k, v in self._store.items()
                if k.startswith(self._path + "/") and "/" not in k[len(self._path) + 1:]]
        for f in self._filters:
            rows = [(k, v) for k, v in rows if v.get(f.field) == f.value]
        if self._order:
            rows.sort(key=lambda kv: kv[1].get(self._order) or 0, reverse=self._desc)
        if self._limit:
            rows = rows[:self._limit]
        return [_Snap(k.split("/")[-1], v) for k, v in rows]

    def stream(self):
        # Like get(), but each snapshot carries a .reference for batch deletes.
        snaps = self.get()
        for s in snaps:
            s.reference = _Doc(self._store, f"{self._path}/{s.id}")
        return snaps


class _Txn:
    """Firestore transactions expose set/update taking an explicit ref; writes
    land immediately here, which is fine — these tests have one writer."""

    def set(self, ref, data):
        ref.set(data)

    def update(self, ref, fields):
        ref.update(fields)


class _Batch:
    """Firestore WriteBatch: queue deletes, apply on commit."""

    def __init__(self):
        self._ops = []

    def delete(self, ref):
        self._ops.append(ref)

    def commit(self):
        for ref in self._ops:
            ref.delete()
        self._ops = []


class _Client:
    def __init__(self, store):
        self._store = store

    def collection(self, name):
        return _Coll(self._store, name)

    def transaction(self):
        return _Txn()

    def batch(self):
        return _Batch()


class _Inc:
    def __init__(self, n):
        self.n = n

    def apply(self, cur):
        return (cur or 0) + self.n


class _ArrayUnion:
    def __init__(self, values):
        self.values = values


class _Filter:
    def __init__(self, field, op, value):
        self.field, self.op, self.value = field, op, value


class _FakeFirestore:
    Increment = _Inc
    ArrayUnion = _ArrayUnion
    FieldFilter = _Filter

    class Query:
        DESCENDING = "DESCENDING"

    @staticmethod
    def transactional(fn):
        return fn


@pytest.fixture
def store(monkeypatch):
    data: dict = {}
    monkeypatch.setattr(chat_repo, "db", lambda: _Client(data))
    monkeypatch.setattr(chat_repo, "firestore", _FakeFirestore)
    return data


# --------------------------------------------------------------------------- #

def test_new_thread_id_shape():
    from datetime import datetime, timezone
    tid = chat_repo.new_thread_id(datetime(2026, 7, 15, tzinfo=timezone.utc), rand="abc123")
    assert tid == "ct_20260715_abc123"


def test_create_thread_and_read_back(store):
    tid = chat_repo.create_thread(ChatThread(requestedBy="me@example.com"))
    thread = chat_repo.get_thread(tid)
    assert thread.requestedBy == "me@example.com"
    assert thread.status == "active"
    assert thread.createdAt is not None


def test_get_missing_thread_is_none(store):
    assert chat_repo.get_thread("ct_nope") is None


def test_append_message_allocates_dense_seq(store):
    tid = chat_repo.create_thread(ChatThread())
    ids = [chat_repo.append_message(tid, ChatMessage(role="user", content=f"m{i}"))
           for i in range(3)]
    assert len(set(ids)) == 3
    assert [m.seq for m in chat_repo.list_messages(tid)] == [0, 1, 2]
    assert chat_repo.get_thread(tid).totals.messages == 3


def test_append_message_to_missing_thread_raises(store):
    with pytest.raises(ValueError):
        chat_repo.append_message("ct_nope", ChatMessage(role="user"))


def test_list_messages_orders_by_seq_not_insertion(store):
    tid = chat_repo.create_thread(ChatThread())
    chat_repo.append_message(tid, ChatMessage(role="user", content="first"))
    chat_repo.append_message(tid, ChatMessage(role="assistant", content="second"))
    assert [m.content for m in chat_repo.list_messages(tid)] == ["first", "second"]


def test_cancel_flag_roundtrip(store):
    tid = chat_repo.create_thread(ChatThread())
    assert chat_repo.is_cancelled(tid) is False
    assert chat_repo.request_cancel(tid) is True
    assert chat_repo.is_cancelled(tid) is True
    chat_repo.clear_cancel(tid)
    assert chat_repo.is_cancelled(tid) is False


def test_request_cancel_on_missing_thread_is_false(store):
    assert chat_repo.request_cancel("ct_nope") is False


def test_recent_history_excludes_unfinished_and_trims(store):
    tid = chat_repo.create_thread(ChatThread())
    chat_repo.append_message(tid, ChatMessage(role="user", content="keep1"))
    chat_repo.append_message(tid, ChatMessage(
        role="assistant", content="half-written",
        status=ChatMessageStatus.streaming.value))
    chat_repo.append_message(tid, ChatMessage(
        role="assistant", content="blew up", status=ChatMessageStatus.error.value))
    chat_repo.append_message(tid, ChatMessage(role="user", content="keep2"))

    history = chat_repo.recent_history(tid, limit=10)
    assert history == [{"role": "user", "content": "keep1"},
                       {"role": "user", "content": "keep2"}]


def test_recent_history_keeps_the_last_n(store):
    tid = chat_repo.create_thread(ChatThread())
    for i in range(6):
        chat_repo.append_message(tid, ChatMessage(role="user", content=f"m{i}"))
    history = chat_repo.recent_history(tid, limit=2)
    assert [h["content"] for h in history] == ["m4", "m5"]


def test_finish_message_writes_terminal_fields(store):
    from app.chat.schemas import ChatSource
    tid = chat_repo.create_thread(ChatThread())
    mid = chat_repo.append_message(tid, ChatMessage(
        role="assistant", status=ChatMessageStatus.streaming.value))
    chat_repo.finish_message(tid, mid, content="final", status="complete",
                             sources=[ChatSource(n=1, url="https://a", title="A")],
                             usage={"costUsd": 0.2})
    msg = chat_repo.get_message(tid, mid)
    assert msg.status == "complete"
    assert msg.content == "final"
    assert msg.sources[0].url == "https://a"
    assert msg.usage.costUsd == 0.2


def test_append_handoff_accumulates(store):
    from app.chat.schemas import ChatHandoff
    tid = chat_repo.create_thread(ChatThread())
    mid = chat_repo.append_message(tid, ChatMessage(role="assistant"))
    chat_repo.append_handoff(tid, mid, ChatHandoff(format="short", refId="post_1"))
    chat_repo.append_handoff(tid, mid, ChatHandoff(format="report", refId="rr_1"))
    msg = chat_repo.get_message(tid, mid)
    assert [(h.format, h.refId) for h in msg.handoffs] == [("short", "post_1"), ("report", "rr_1")]


def test_usage_rollup_increments(store):
    chat_repo.add_usage(0.25, month="2026-07")
    chat_repo.add_usage(0.10, month="2026-07")
    assert store["chatUsage/2026-07"] == {"costUsd": 0.35, "messages": 2}


def test_thread_cost_increments(store):
    tid = chat_repo.create_thread(ChatThread())
    chat_repo.add_thread_cost(tid, 0.4)
    chat_repo.add_thread_cost(tid, 0.1)
    assert chat_repo.get_thread(tid).totals.costUsd == pytest.approx(0.5)


# --------------------------------------------------------------------------- #
# Thread management: rename / archive / delete                                #
# --------------------------------------------------------------------------- #

def test_rename_thread(store):
    tid = chat_repo.create_thread(ChatThread())
    assert chat_repo.rename_thread(tid, "New title") is True
    assert chat_repo.get_thread(tid).title == "New title"


def test_rename_thread_caps_length(store):
    tid = chat_repo.create_thread(ChatThread())
    chat_repo.rename_thread(tid, "x" * 200)
    assert len(chat_repo.get_thread(tid).title) == 80


def test_rename_missing_thread_is_false(store):
    assert chat_repo.rename_thread("ct_nope", "x") is False


def test_set_thread_status_archives_and_hides_from_list(store):
    tid = chat_repo.create_thread(ChatThread())
    assert chat_repo.set_thread_status(tid, "archived") is True
    assert chat_repo.get_thread(tid).status == "archived"
    assert tid not in [t.id for t in chat_repo.list_threads()]


def test_set_thread_status_missing_is_false(store):
    assert chat_repo.set_thread_status("ct_nope", "archived") is False


def test_delete_thread_removes_thread_and_messages(store):
    tid = chat_repo.create_thread(ChatThread())
    chat_repo.append_message(tid, ChatMessage(role="user", content="a"))
    chat_repo.append_message(tid, ChatMessage(role="assistant", content="b"))
    assert chat_repo.delete_thread(tid) is True
    assert chat_repo.get_thread(tid) is None
    assert chat_repo.list_messages(tid) == []
    # the whole subtree is gone, not just the thread document
    assert [k for k in store if tid in k] == []


def test_delete_missing_thread_is_false(store):
    assert chat_repo.delete_thread("ct_nope") is False
