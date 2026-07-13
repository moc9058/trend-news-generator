from fastapi.testclient import TestClient

import app.main as main
from app.models import ChannelState, ChannelStatus, Format, Post, PostStatus

client = TestClient(main.app)


def _post(status=PostStatus.draft, channel_status=ChannelStatus.pending):
    return Post(
        id="p1", format=Format.article, categoryId="science-technology",
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
    triggered = []
    monkeypatch.setattr(main, "_trigger_job", lambda name: triggered.append(name))
    resp = client.post("/api/jobs/generate_short/run")
    assert resp.status_code == 202
    # response carries the Cloud Run Job name; the trigger got the API name
    assert resp.json() == {"accepted": True, "job": "job-generate-short"}
    assert triggered == ["generate_short"]


def test_run_job_trigger_failure_is_502(monkeypatch):
    def boom(_name):
        raise RuntimeError("metadata server unreachable")

    monkeypatch.setattr(main, "_trigger_job", boom)
    resp = client.post("/api/jobs/collect/run")
    assert resp.status_code == 502
    assert "job-collect" in resp.json()["detail"]


def test_cloud_run_job_name_mapping():
    assert main._cloud_run_job_name("generate_short") == "job-generate-short"
    assert main._cloud_run_job_name("collect") == "job-collect"
