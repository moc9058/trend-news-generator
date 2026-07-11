from fastapi.testclient import TestClient

import app.main as main
from app.models import Cadence, ChannelState, ChannelStatus, Post, PostStatus

client = TestClient(main.app)


def _post(status=PostStatus.draft, channel_status=ChannelStatus.pending):
    return Post(
        id="p1", cadence=Cadence.weekly, categoryId="science-technology",
        status=status, title="T",
        channels={
            "x": ChannelState(enabled=True, status=channel_status),
            "notion": ChannelState(enabled=True, status=channel_status),
        },
    )


def test_healthz():
    assert client.get("/healthz").json() == {"ok": True}


def test_publish_404(monkeypatch):
    monkeypatch.setattr(main.posts, "get", lambda _id: None)
    assert client.post("/api/posts/x/publish", json={}).status_code == 404


def test_publish_conflict_when_already_published(monkeypatch):
    monkeypatch.setattr(main.posts, "get", lambda _id: _post(PostStatus.published))
    assert client.post("/api/posts/p1/publish", json={}).status_code == 409


def test_publish_flow(monkeypatch):
    updates = {}
    monkeypatch.setattr(main.posts, "get", lambda _id: _post())
    monkeypatch.setattr(main.posts, "update_fields", lambda _id, f: updates.update(f))
    monkeypatch.setattr(main.posts, "update_channel", lambda *_a: None)

    published = _post(PostStatus.published, ChannelStatus.published)
    monkeypatch.setattr(main, "publish_post", lambda _id, only_channel="": published)

    resp = client.post("/api/posts/p1/publish", json={"approvedBy": "moc9058@gmail.com"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "published"
    assert updates["approvedBy"] == "moc9058@gmail.com"


def test_retry_channel_requires_failed_state(monkeypatch):
    monkeypatch.setattr(main.posts, "get", lambda _id: _post())
    resp = client.post("/api/posts/p1/retry-channel", json={"channel": "x"})
    assert resp.status_code == 409


def test_retry_unknown_channel(monkeypatch):
    monkeypatch.setattr(main.posts, "get", lambda _id: _post())
    resp = client.post("/api/posts/p1/retry-channel", json={"channel": "mastodon"})
    assert resp.status_code == 400


def test_run_unknown_job():
    assert client.post("/api/jobs/nope/run").status_code == 400


def test_run_job_accepted(monkeypatch):
    ran = []
    monkeypatch.setitem(main.JOB_MODULES, "collect", "fake.module")
    monkeypatch.setattr(main, "_run_job", lambda m: ran.append(m))
    resp = client.post("/api/jobs/collect/run")
    assert resp.status_code == 202
    assert ran == ["fake.module"]
