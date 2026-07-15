"""FirestoreCheckpointSaver against an in-memory Firestore (design §6.1).

This class implements a third-party ABI by hand, so it is the component most
exposed to a langgraph-checkpoint bump: these tests are the canary. They cover the
storage model's real hazards — chunking past Firestore's 1MiB document limit,
pydantic values surviving a round-trip, ordering, and the idempotency Pregel
relies on when it retries a write.
"""

import pytest
from google.cloud import firestore
from langgraph.checkpoint.base import Checkpoint, CheckpointMetadata, empty_checkpoint

from app.research.graph.checkpointer import CHUNK_BYTES, FirestoreCheckpointSaver
from app.research.schemas import BudgetState, ResearchRun


# --------------------------------------------------------------------------- #
# Minimal in-memory Firestore                                                  #
# --------------------------------------------------------------------------- #

class _Snap:
    def __init__(self, doc_id, data):
        self.id, self._data = doc_id, data
        self.exists = data is not None

    def to_dict(self):
        return self._data


class _Query:
    def __init__(self, store, path, filters=None, order=None, desc=False, limit=None):
        self._store, self._path = store, path
        self._filters = list(filters or [])
        self._order, self._desc, self._limit = order, desc, limit

    def _clone(self, **kw):
        base = dict(filters=self._filters, order=self._order,
                    desc=self._desc, limit=self._limit)
        base.update(kw)
        return _Query(self._store, self._path, **base)

    def where(self, filter=None, **kw):  # noqa: A002 — mirrors the firestore API
        return self._clone(filters=self._filters + [filter])

    def order_by(self, field, direction=None):
        return self._clone(order=field, desc=(direction == firestore.Query.DESCENDING))

    def limit(self, n):
        return self._clone(limit=n)

    def _rows(self):
        rows = [(doc_id, data) for path, doc_id, data in self._store.rows()
                if path == self._path]
        for f in self._filters:
            field, op, val = f.field_path, f.op_string, f.value
            def keep(item, field=field, op=op, val=val):
                got = item[1].get(field)
                if op == "==":
                    return got == val
                if op == "<":
                    return got < val
                raise AssertionError(f"unsupported op {op}")
            rows = [r for r in rows if keep(r)]
        if self._order:
            rows.sort(key=lambda r: r[1].get(self._order), reverse=self._desc)
        if self._limit is not None:
            rows = rows[: self._limit]
        return rows

    def stream(self):
        return iter([_Snap(doc_id, data) for doc_id, data in self._rows()])

    def get(self):
        return list(self.stream())

    def document(self, doc_id):
        return _DocRef(self._store, self._path, doc_id)


class _DocRef:
    def __init__(self, store, coll_path, doc_id):
        self._store, self._coll_path, self.id = store, coll_path, doc_id
        self.path = f"{coll_path}/{doc_id}"

    def collection(self, name):
        return _Query(self._store, f"{self.path}/{name}")

    def set(self, data):
        self._store.data[self.path] = dict(data)

    def get(self):
        return _Snap(self.id, self._store.data.get(self.path))

    def delete(self):
        self._store.data.pop(self.path, None)


class FakeFirestore:
    def __init__(self):
        self.data: dict[str, dict] = {}

    def collection(self, name):
        return _Query(self, name)

    def rows(self):
        for path, data in list(self.data.items()):
            coll, _, doc_id = path.rpartition("/")
            yield coll, doc_id, data


# --------------------------------------------------------------------------- #

@pytest.fixture
def saver():
    return FirestoreCheckpointSaver(client=FakeFirestore(), ttl_days=14)


def _cfg(thread_id="rr_1", checkpoint_id=None):
    conf = {"thread_id": thread_id, "checkpoint_ns": ""}
    if checkpoint_id:
        conf["checkpoint_id"] = checkpoint_id
    return {"configurable": conf}


def _ckpt(checkpoint_id="1ef00000-0000-6000-8000-000000000001", **values) -> Checkpoint:
    c = empty_checkpoint()
    c["id"] = checkpoint_id
    c["channel_values"] = values
    return c


def _meta(step=1) -> CheckpointMetadata:
    return CheckpointMetadata(source="loop", step=step, parents={})


# ---- round-trip ------------------------------------------------------------

def test_put_get_round_trip(saver):
    saver.put(_cfg(), _ckpt(hello="world"), _meta(step=3), {})
    got = saver.get_tuple(_cfg())

    assert got is not None
    assert got.checkpoint["channel_values"] == {"hello": "world"}
    assert got.metadata["step"] == 3
    assert got.config["configurable"]["checkpoint_id"] == \
        "1ef00000-0000-6000-8000-000000000001"


def test_pydantic_values_round_trip(saver):
    """Channels hold pydantic models; JsonPlusSerializer must return models, not dicts."""
    run = ResearchRun(id="rr_1", theme="テーマ", budget=BudgetState(usdCap=10.0),
                      languages=["ja", "ko"], status="running", phase="plan")
    saver.put(_cfg(), _ckpt(run=run, budget=run.budget), _meta(), {})

    got = saver.get_tuple(_cfg())
    restored = got.checkpoint["channel_values"]["run"]
    assert isinstance(restored, ResearchRun)
    assert restored.theme == "テーマ" and restored.languages == ["ja", "ko"]
    assert isinstance(restored.budget, BudgetState)
    assert restored.budget.usdCap == 10.0


def test_every_schema_model_survives_the_serde_allowlist(saver):
    """An unlisted type does not raise — it comes back as a dict. Hence this test.

    JsonPlusSerializer's strict path silently degrades unknown pydantic models to
    plain dicts, so a missing allowlist entry would surface far away as an
    AttributeError inside a phase, on a resume, in production. Round-trip every
    model the schemas module defines and assert the class survives.
    """
    import inspect

    from pydantic import BaseModel

    from app.research import schemas

    models = [obj for _, obj in inspect.getmembers(schemas, inspect.isclass)
              if issubclass(obj, BaseModel) and obj is not BaseModel]
    assert len(models) > 10, "guard the guard: the model sweep found almost nothing"

    for model in models:
        try:
            instance = model()
        except Exception:
            continue  # requires args; the nested cases below cover the shapes
        saver.put(_cfg("rr_types"), _ckpt(v=instance), _meta(), {})
        got = saver.get_tuple(_cfg("rr_types"))
        restored = got.checkpoint["channel_values"]["v"]
        assert isinstance(restored, model), (
            f"{model.__name__} came back as {type(restored).__name__} — add it to "
            "checkpointer._allowed_types()")


def test_nested_models_survive_inside_a_container(saver):
    """Channels hold lists/dicts of models; each nested class needs the allowlist."""
    from app.research.schemas import Claim, CoverageReport, RqCoverage

    coverage = CoverageReport(loops=1, decision="finalize",
                              rqCoverage=[RqCoverage(rqId="rq1", evidence=2,
                                                     resolved=True)])
    claims = [Claim(claimId="c1", text="x", verdict="corroborated")]
    saver.put(_cfg(), _ckpt(coverage=coverage, claims=claims), _meta(), {})

    got = saver.get_tuple(_cfg()).checkpoint["channel_values"]
    assert isinstance(got["coverage"], CoverageReport)
    assert isinstance(got["coverage"].rqCoverage[0], RqCoverage)
    assert got["coverage"].rqCoverage[0].rqId == "rq1"
    assert isinstance(got["claims"][0], Claim)


def test_large_state_is_chunked_and_restored_byte_exact(saver):
    """kokkai hits carry full speech text, so state really does exceed 1MiB.

    A Firestore document caps at ~1MiB; without chunking a big run could not
    checkpoint at all.
    """
    big = "国" * 1_200_000  # ~3.6MB as UTF-8
    saver.put(_cfg(), _ckpt(blob=big), _meta(), {})

    meta = saver._client.data["researchRuns/rr_1/checkpoints/"
                              "1ef00000-0000-6000-8000-000000000001"]
    assert meta["chunkCount"] > 1
    for i in range(meta["chunkCount"]):
        chunk = saver._client.data[
            f"researchRuns/rr_1/checkpoints/1ef00000-0000-6000-8000-000000000001"
            f"/checkpoint_chunks/{i}"]
        assert len(chunk["data"]) <= CHUNK_BYTES

    got = saver.get_tuple(_cfg())
    assert got.checkpoint["channel_values"]["blob"] == big


def test_missing_chunk_raises_rather_than_returning_a_truncated_state(saver):
    """A silently short state would resume the graph with wrong data."""
    saver.put(_cfg(), _ckpt(blob="x" * (CHUNK_BYTES * 2)), _meta(), {})
    # drop the second chunk
    del saver._client.data["researchRuns/rr_1/checkpoints/"
                           "1ef00000-0000-6000-8000-000000000001/checkpoint_chunks/1"]
    with pytest.raises(ValueError, match="chunk"):
        saver.get_tuple(_cfg())


def test_put_is_idempotent_for_the_same_checkpoint_id(saver):
    saver.put(_cfg(), _ckpt(v=1), _meta(), {})
    saver.put(_cfg(), _ckpt(v=2), _meta(), {})  # same id, retried

    ckpts = [p for p in saver._client.data
             if p.startswith("researchRuns/rr_1/checkpoints/")
             and "/checkpoint_chunks/" not in p]
    assert len(ckpts) == 1
    assert saver.get_tuple(_cfg()).checkpoint["channel_values"] == {"v": 2}


# ---- ordering / parents ----------------------------------------------------

def _put_series(saver, n=3):
    ids = [f"1ef00000-0000-6000-8000-00000000000{i}" for i in range(1, n + 1)]
    parent = None
    for i, cid in enumerate(ids):
        saver.put(_cfg(checkpoint_id=parent), _ckpt(cid, step=i), _meta(step=i), {})
        parent = cid
    return ids


def test_get_tuple_without_id_returns_the_latest(saver):
    ids = _put_series(saver)
    got = saver.get_tuple(_cfg())
    assert got.config["configurable"]["checkpoint_id"] == ids[-1]


def test_parent_config_chains_to_the_previous_checkpoint(saver):
    ids = _put_series(saver)
    got = saver.get_tuple(_cfg())
    assert got.parent_config["configurable"]["checkpoint_id"] == ids[-2]

    first = saver.get_tuple(_cfg(checkpoint_id=ids[0]))
    assert first.parent_config is None


def test_list_orders_desc_and_honours_before_and_limit(saver):
    ids = _put_series(saver, 4)

    listed = [t.config["configurable"]["checkpoint_id"] for t in saver.list(_cfg())]
    assert listed == list(reversed(ids))

    limited = list(saver.list(_cfg(), limit=2))
    assert [t.config["configurable"]["checkpoint_id"] for t in limited] == \
        list(reversed(ids))[:2]

    before = list(saver.list(_cfg(), before=_cfg(checkpoint_id=ids[2])))
    assert [t.config["configurable"]["checkpoint_id"] for t in before] == \
        [ids[1], ids[0]]


def test_list_filters_on_metadata(saver):
    _put_series(saver, 3)
    only = list(saver.list(_cfg(), filter={"step": 1}))
    assert len(only) == 1 and only[0].metadata["step"] == 1


def test_get_tuple_returns_none_for_unknown_thread_or_checkpoint(saver):
    assert saver.get_tuple(_cfg("nope")) is None
    saver.put(_cfg(), _ckpt(), _meta(), {})
    assert saver.get_tuple(_cfg(checkpoint_id="does-not-exist")) is None


# ---- writes ----------------------------------------------------------------

def test_put_writes_round_trip(saver):
    cfg = _cfg(checkpoint_id="ck1")
    saver.put_writes(cfg, [("channel_a", {"x": 1}), ("channel_b", [1, 2])], "task-1")

    saver.put(_cfg(), _ckpt("ck1"), _meta(), {})
    got = saver.get_tuple(_cfg(checkpoint_id="ck1"))
    assert sorted(got.pending_writes, key=lambda w: w[1]) == [
        ("task-1", "channel_a", {"x": 1}),
        ("task-1", "channel_b", [1, 2]),
    ]


def test_put_writes_special_channels_overwrite_instead_of_duplicating(saver):
    """Pregel retries a failed task; WRITES_IDX_MAP pins __error__ to one slot."""
    cfg = _cfg(checkpoint_id="ck1")
    saver.put_writes(cfg, [("__error__", "boom-1")], "task-1")
    saver.put_writes(cfg, [("__error__", "boom-2")], "task-1")

    saver.put(_cfg(), _ckpt("ck1"), _meta(), {})
    writes = saver.get_tuple(_cfg(checkpoint_id="ck1")).pending_writes
    assert writes == [("task-1", "__error__", "boom-2")]


def test_writes_of_different_tasks_coexist(saver):
    cfg = _cfg(checkpoint_id="ck1")
    saver.put_writes(cfg, [("ch", 1)], "task-1")
    saver.put_writes(cfg, [("ch", 2)], "task-2")

    saver.put(_cfg(), _ckpt("ck1"), _meta(), {})
    writes = saver.get_tuple(_cfg(checkpoint_id="ck1")).pending_writes
    assert len(writes) == 2
    assert {w[0] for w in writes} == {"task-1", "task-2"}


def test_large_write_is_chunked(saver):
    cfg = _cfg(checkpoint_id="ck1")
    big = "y" * (CHUNK_BYTES + 10)
    saver.put_writes(cfg, [("ch", big)], "task-1")
    saver.put(_cfg(), _ckpt("ck1"), _meta(), {})

    writes = saver.get_tuple(_cfg(checkpoint_id="ck1")).pending_writes
    assert writes[0][2] == big


# ---- lifecycle -------------------------------------------------------------

def test_delete_thread_removes_checkpoints_writes_and_chunks(saver):
    saver.put(_cfg(), _ckpt(blob="z" * (CHUNK_BYTES * 2)), _meta(), {})
    saver.put_writes(_cfg(checkpoint_id="1ef00000-0000-6000-8000-000000000001"),
                     [("ch", "v")], "task-1")
    assert saver._client.data

    saver.delete_thread("rr_1")

    leftovers = [p for p in saver._client.data if p.startswith("researchRuns/rr_1/")]
    assert leftovers == []


def test_delete_thread_leaves_other_runs_alone(saver):
    saver.put(_cfg("rr_1"), _ckpt(), _meta(), {})
    saver.put(_cfg("rr_2"), _ckpt(), _meta(), {})

    saver.delete_thread("rr_1")

    assert not [p for p in saver._client.data if p.startswith("researchRuns/rr_1/")]
    assert [p for p in saver._client.data if p.startswith("researchRuns/rr_2/")]


def test_ttl_is_stamped_on_every_document(saver):
    """The TTL policy is what keeps abandoned threads from accumulating."""
    saver.put(_cfg(), _ckpt(blob="q" * 10), _meta(), {})
    saver.put_writes(_cfg(checkpoint_id="1ef00000-0000-6000-8000-000000000001"),
                     [("ch", "v")], "task-1")

    for path, data in saver._client.data.items():
        assert "expiresAt" in data, path


def test_async_methods_are_not_implemented(saver):
    """The graph is sync on purpose; a sync-over-async shim would invite deadlock."""
    import asyncio

    with pytest.raises(NotImplementedError):
        asyncio.run(saver.aget_tuple(_cfg()))
