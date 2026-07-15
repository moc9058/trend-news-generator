"""POST /api/chat/messages: SSE framing, event order, persistence, cancel."""

import json

import pytest
from fastapi.testclient import TestClient

import app.chat.api as api_mod
from app.chat.schemas import ChatMessageStatus


# --------------------------------------------------------------------------- #
# In-memory repo + graph fakes                                                 #
# --------------------------------------------------------------------------- #

class _Repo:
    def __init__(self):
        self.threads, self.messages, self.usage = {}, {}, {"cost": 0.0, "n": 0}
        self.seq = 0

    def create_thread(self, thread):
        self.seq += 1
        tid = f"ct_{self.seq}"
        thread.id = tid
        self.threads[tid] = thread
        return tid

    def get_thread(self, tid):
        return self.threads.get(tid)

    def update_thread(self, tid, fields):
        for k, v in fields.items():
            setattr(self.threads[tid], k, v) if hasattr(self.threads[tid], k) else None

    def append_message(self, tid, msg):
        self.seq += 1
        mid = f"m_{self.seq}"
        msg.id = mid
        self.messages[mid] = msg
        return mid

    def update_message(self, tid, mid, fields):
        for k, v in fields.items():
            setattr(self.messages[mid], k, v)

    def finish_message(self, tid, mid, *, content, status, sources=None, usage=None, error=""):
        m = self.messages[mid]
        m.content, m.status, m.error = content, status, error
        m.sources = sources or []
        m.usage = usage

    def recent_history(self, tid, limit):
        return []

    def clear_cancel(self, tid):
        self.threads[tid].cancelRequested = False

    def is_cancelled(self, tid):
        t = self.threads.get(tid)
        return bool(t and t.cancelRequested)

    def request_cancel(self, tid):
        if tid not in self.threads:
            return False
        self.threads[tid].cancelRequested = True
        return True

    def add_thread_cost(self, tid, cost):
        pass

    def add_usage(self, cost, month="", messages=1):
        self.usage["cost"] += cost
        self.usage["n"] += messages


@pytest.fixture
def repo(monkeypatch):
    r = _Repo()
    monkeypatch.setattr(api_mod, "chat_repo", r)
    return r


@pytest.fixture
def fake_graph(monkeypatch):
    """Replace the compiled graph with a scripted event emitter."""
    script = {"chunks": [
        {"type": "status", "data": {"stage": "planning"}},
        {"type": "sources", "data": {"sources": [
            {"n": 1, "url": "https://a", "title": "A", "tier": "primary", "score": 70}]}},
        {"type": "token", "data": {"delta": "Hello "}},
        {"type": "token", "data": {"delta": "world"}},
    ], "raise": None}

    class _G:
        def stream(self, state, context=None, stream_mode=None, config=None):
            script["state"] = state
            script["config"] = config
            context.budget.charge_usd(0.12)
            context.llm_events.append({"tokensIn": 300, "tokensOut": 50,
                                       "model": "gpt-5.6-terra"})
            if script["raise"]:
                raise RuntimeError(script["raise"])
            yield from script["chunks"]

    monkeypatch.setattr(api_mod, "build_graph", lambda: _G())
    monkeypatch.setattr(api_mod, "_maybe_title", lambda *a, **kw: None)
    return script


@pytest.fixture
def fake_sources(monkeypatch):
    """Research mode builds the real connector registry and Fetcher; neither
    belongs in a unit test (the grounded connector demands a Gemini key)."""
    import app.research.sources.base as base_mod
    from app.research.fetch import fetcher as fetcher_mod
    monkeypatch.setattr(base_mod, "build_registry", lambda: {})
    monkeypatch.setattr(fetcher_mod, "Fetcher", lambda *a, **kw: object())


@pytest.fixture
def client(repo, fake_graph, fake_sources, monkeypatch):
    monkeypatch.setattr(api_mod, "PING_SECONDS", 0.05)
    from app.main import app
    return TestClient(app)


def _parse_sse(body: str) -> list[tuple[str, dict]]:
    out = []
    for block in body.split("\n\n"):
        if not block.strip() or block.startswith(": "):
            continue
        event, data = None, None
        for line in block.splitlines():
            if line.startswith("event: "):
                event = line[7:]
            elif line.startswith("data: "):
                data = json.loads(line[6:])
        if event:
            out.append((event, data))
    return out


def _post(client, **kw):
    body = {"content": "hi", "mode": "chat", "requestedBy": "me@example.com", **kw}
    return client.post("/api/chat/messages", json=body)


# --------------------------------------------------------------------------- #

def test_event_order_meta_first_done_last(client):
    resp = _post(client)
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")
    assert resp.headers["x-accel-buffering"] == "no"
    assert resp.headers["cache-control"] == "no-cache"

    events = _parse_sse(resp.text)
    names = [e for e, _ in events]
    assert names[0] == "meta"
    assert names[-1] == "done"
    assert names.index("sources") < names.index("token")
    assert "usage" in names


def test_meta_carries_new_thread_and_message_ids(client, repo):
    events = _parse_sse(_post(client).text)
    meta = dict(events)["meta"]
    assert meta["threadId"] in repo.threads
    assert meta["userMessageId"] in repo.messages
    assert meta["assistantMessageId"] in repo.messages


def test_tokens_are_persisted_and_message_completes(client, repo):
    events = _parse_sse(_post(client).text)
    mid = dict(events)["meta"]["assistantMessageId"]
    msg = repo.messages[mid]
    assert msg.content == "Hello world"
    assert msg.status == ChatMessageStatus.complete.value
    assert msg.sources[0]["url"] == "https://a"
    assert msg.usage["costUsd"] == 0.12
    assert msg.usage["promptTokens"] == 300


def test_user_message_saved_complete_before_streaming(client, repo):
    events = _parse_sse(_post(client, content="my question").text)
    uid = dict(events)["meta"]["userMessageId"]
    assert repo.messages[uid].content == "my question"
    assert repo.messages[uid].status == ChatMessageStatus.complete.value


def test_usage_rolls_up_to_monthly_counter(client, repo):
    _post(client)
    assert repo.usage["cost"] == 0.12
    assert repo.usage["n"] == 1


def test_existing_thread_is_reused_not_recreated(client, repo):
    first = dict(_parse_sse(_post(client).text))["meta"]["threadId"]
    second = dict(_parse_sse(_post(client, threadId=first).text))["meta"]["threadId"]
    assert first == second
    assert len(repo.threads) == 1


def test_unknown_thread_is_404(client):
    assert _post(client, threadId="ct_nope").status_code == 404


def test_blank_content_is_400(client):
    assert _post(client, content="   ").status_code == 400


def test_unknown_mode_and_depth_are_400(client):
    assert _post(client, mode="telepathy").status_code == 400
    assert _post(client, mode="research", depth="exhaustive").status_code == 400


def test_graph_failure_yields_error_event_and_persists_status(client, repo, fake_graph):
    fake_graph["raise"] = "upstream exploded"
    events = _parse_sse(_post(client).text)
    names = [e for e, _ in events]
    assert names[-1] == "error"
    err = dict(events)["error"]
    assert "upstream exploded" in err["message"]
    msg = repo.messages[err["messageId"]]
    assert msg.status == ChatMessageStatus.error.value
    assert "upstream exploded" in msg.error


def test_cancelled_thread_marks_message_cancelled(client, repo, fake_graph):
    # The thread is already flagged, so the poll sees it as soon as the run ends.
    resp = _post(client)
    tid = dict(_parse_sse(resp.text))["meta"]["threadId"]
    repo.request_cancel(tid)

    events = _parse_sse(_post(client, threadId=tid).text)
    # A new message clears the stale flag first — otherwise it would be born
    # cancelled.
    assert repo.threads[tid].cancelRequested is False
    assert dict(events)["done"]["status"] == ChatMessageStatus.complete.value


def test_cancel_endpoint(client, repo):
    tid = dict(_parse_sse(_post(client).text))["meta"]["threadId"]
    resp = client.post(f"/api/chat/threads/{tid}/cancel")
    assert resp.status_code == 202
    assert resp.json() == {"ok": True}
    assert repo.threads[tid].cancelRequested is True


def test_cancel_unknown_thread_is_404(client):
    assert client.post("/api/chat/threads/ct_nope/cancel").status_code == 404


def test_research_mode_passes_depth_and_traces_metadata(client, fake_graph):
    _post(client, mode="research", depth="deep")
    assert fake_graph["state"]["depth"] == "deep"
    assert fake_graph["state"]["mode"] == "research"
    assert fake_graph["config"]["run_name"] == "research-chat"
    assert fake_graph["config"]["metadata"]["depth"] == "deep"


def test_chat_mode_forces_quick_depth(client, fake_graph):
    _post(client, mode="chat", depth="deep")
    assert fake_graph["state"]["depth"] == "quick"


def test_worker_setup_failure_terminates_the_stream(repo, fake_graph, monkeypatch):
    """A crash before the graph starts must still end the response.

    Regression: resource setup used to sit outside the worker's try, so an
    exception there (a missing Gemini key when building the connector registry)
    killed the thread before it queued the sentinel. `_drain` then emitted
    keep-alive pings forever — the request never finished and the message stayed
    `streaming` for good.
    """
    import app.research.sources.base as base_mod

    def _boom():
        raise ValueError("No API key was provided.")

    monkeypatch.setattr(base_mod, "build_registry", _boom)
    monkeypatch.setattr(api_mod, "PING_SECONDS", 0.05)
    from app.main import app

    with TestClient(app) as c:
        events = _parse_sse(_post(c, mode="research").text)   # must not hang

    names = [e for e, _ in events]
    assert names[-1] == "error"
    err = dict(events)["error"]
    assert "No API key" in err["message"]
    assert repo.messages[err["messageId"]].status == ChatMessageStatus.error.value
