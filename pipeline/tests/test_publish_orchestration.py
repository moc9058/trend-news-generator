"""Idempotency and crash-recovery behaviour of the publish orchestrator."""

import pytest

import app.publishers.base as base
from app.models import (
    AppSettings,
    ChannelState,
    ChannelStatus,
    Format,
    Post,
    PostStatus,
)


@pytest.fixture
def store(monkeypatch):
    """In-memory stand-ins for Firestore and the channel adapters."""
    state = {"post": None, "statuses": [], "channel_updates": [], "calls": []}

    monkeypatch.setattr(base.posts, "get", lambda _id: state["post"])
    monkeypatch.setattr(
        base.posts, "set_status",
        lambda _id, s, **kw: state["statuses"].append(s),
    )
    monkeypatch.setattr(
        base.posts, "update_channel",
        lambda _id, ch, st: state["channel_updates"].append((ch, st.status)),
    )
    monkeypatch.setattr(base.configs, "app_settings", lambda: AppSettings(attachImages=False))
    monkeypatch.setattr(base.configs, "enabled_categories", lambda: [])

    monkeypatch.setattr(
        base.notion, "publish",
        lambda *a, **k: (state["calls"].append("notion"), ("page-1", "https://notion.so/p"))[1],
    )
    monkeypatch.setattr(
        base.x, "publish",
        lambda *a, **k: (state["calls"].append("x"), "tweet-1")[1],
    )
    monkeypatch.setattr(
        base.threads, "create_container",
        lambda *a, **k: (state["calls"].append("th-create"), "container-1")[1],
    )
    monkeypatch.setattr(base.threads, "wait_until_ready", lambda _c: None)
    monkeypatch.setattr(
        base.threads, "publish_container",
        lambda _c: (state["calls"].append("th-publish"), "media-1")[1],
    )
    return state


def _post(**channels) -> Post:
    return Post(
        id="p1", format=Format.article, categoryId="cat",
        status=PostStatus.approved, title="T", body="Body",
        channels=channels,
    )


def test_publishes_all_channels_notion_first(store):
    store["post"] = _post(
        notion=ChannelState(enabled=True),
        x=ChannelState(enabled=True, text="teaser"),
        threads=ChannelState(enabled=True, text="teaser"),
    )
    result = base.publish_post("p1")
    assert store["calls"] == ["notion", "x", "th-create", "th-publish"]
    assert result.status == PostStatus.published
    assert result.channels["notion"].url == "https://notion.so/p"


def test_skips_channels_with_external_id(store):
    store["post"] = _post(
        notion=ChannelState(enabled=True, externalId="page-old", status=ChannelStatus.published),
        x=ChannelState(enabled=True, text="t"),
    )
    base.publish_post("p1")
    assert store["calls"] == ["x"]


def test_resumes_persisted_threads_container(store):
    store["post"] = _post(
        threads=ChannelState(enabled=True, text="t", containerId="container-old"),
    )
    base.publish_post("p1")
    assert "th-create" not in store["calls"]
    assert store["calls"] == ["th-publish"]


def test_partial_failure_status(store, monkeypatch):
    def boom(*_a, **_k):
        raise RuntimeError("x is down")

    monkeypatch.setattr(base.x, "publish", boom)
    store["post"] = _post(
        notion=ChannelState(enabled=True),
        x=ChannelState(enabled=True, text="t"),
    )
    result = base.publish_post("p1")
    assert result.status == PostStatus.partially_published
    assert result.channels["x"].status == ChannelStatus.failed
    assert "x is down" in result.channels["x"].error


def test_all_failed_status(store, monkeypatch):
    monkeypatch.setattr(
        base.notion, "publish",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no db")),
    )
    store["post"] = _post(notion=ChannelState(enabled=True))
    result = base.publish_post("p1")
    assert result.status == PostStatus.failed


def test_only_channel_retry(store):
    store["post"] = _post(
        notion=ChannelState(enabled=True, externalId="page-1", status=ChannelStatus.published, url="https://notion.so/p"),
        x=ChannelState(enabled=True, text="t"),
    )
    base.publish_post("p1", only_channel="x")
    assert store["calls"] == ["x"]


def test_short_x_gets_no_url(store, monkeypatch):
    captured = {}

    def fake_x_publish(text, **kw):
        captured["text"] = text
        return "tweet-1"

    monkeypatch.setattr(base.x, "publish", fake_x_publish)
    post = _post(
        notion=ChannelState(enabled=True),
        x=ChannelState(enabled=True, text="short brief"),
    )
    post.format = Format.short
    store["post"] = post
    base.publish_post("p1")
    assert "notion.so" not in captured["text"]


def test_article_x_teaser_gets_notion_url(store, monkeypatch):
    captured = {}

    def fake_x_publish(text, **kw):
        captured["text"] = text
        return "tweet-1"

    monkeypatch.setattr(base.x, "publish", fake_x_publish)
    store["post"] = _post(
        notion=ChannelState(enabled=True),
        x=ChannelState(enabled=True, text="article teaser"),
    )
    base.publish_post("p1")
    assert "https://notion.so/p" in captured["text"]
