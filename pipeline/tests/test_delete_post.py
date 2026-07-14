"""Delete orchestration (remote artifact removal) and the /delete endpoint."""

import pytest
from fastapi.testclient import TestClient

import app.main as main
import app.publishers.base as base
from app.models import (
    ChannelState,
    ChannelStatus,
    Format,
    LocalizedContent,
    Post,
    PostStatus,
)

client = TestClient(main.app)


@pytest.fixture
def store(monkeypatch):
    state = {"post": None, "channel_updates": [], "calls": [], "doc_deleted": False}

    monkeypatch.setattr(base.posts, "get", lambda _id: state["post"])
    monkeypatch.setattr(
        base.posts, "update_channel",
        lambda _id, ch, st: state["channel_updates"].append((ch, st.status)),
    )
    monkeypatch.setattr(
        base.posts, "delete",
        lambda _id: state.update(doc_deleted=True),
    )
    monkeypatch.setattr(base.x, "delete", lambda tid: state["calls"].append(("x", tid)))
    monkeypatch.setattr(base.threads, "delete", lambda mid: state["calls"].append(("threads", mid)))
    monkeypatch.setattr(
        base.notion, "archive_page", lambda pid: state["calls"].append(("notion", pid))
    )
    return state


def _published_post(**extra) -> Post:
    return Post(
        id="p1", format=Format.short, categoryId="cat",
        status=PostStatus.published, title="T",
        channels={
            "x": ChannelState(enabled=True, status=ChannelStatus.published, externalId="tw-1"),
            "threads": ChannelState(enabled=True, status=ChannelStatus.published, externalId="th-1"),
            "notion": ChannelState(
                enabled=True, status=ChannelStatus.published,
                externalId="pg-1", pageId="pg-1",
            ),
        },
        **extra,
    )


def test_deletes_all_channels_and_doc(store):
    store["post"] = _published_post()
    result = base.delete_post_channels("p1", None, delete_doc=True)
    assert set(store["calls"]) == {("x", "tw-1"), ("threads", "th-1"), ("notion", "pg-1")}
    assert result["channels"] == {"x": "deleted", "threads": "deleted", "notion": "deleted"}
    assert result["docDeleted"] is True
    assert store["doc_deleted"] is True


def test_deletes_channel_subset_keeps_doc(store):
    store["post"] = _published_post()
    result = base.delete_post_channels("p1", ["x"], delete_doc=False)
    assert store["calls"] == [("x", "tw-1")]
    assert result["channels"] == {"x": "deleted"}
    assert result["docDeleted"] is False
    # subset delete leaves other channels published → deletePost would refuse
    result2 = base.delete_post_channels("p1", ["x"], delete_doc=True)
    assert result2["docDeleted"] is False


def test_report_notion_delete_archives_localized_pages(store):
    post = _published_post()
    post.format = Format.report
    post.localizations = {
        "ja": LocalizedContent(notionPageId="pg-1"),
        "ko": LocalizedContent(notionPageId="pg-ko"),
        "en": LocalizedContent(notionPageId="pg-en"),
    }
    store["post"] = post
    base.delete_post_channels("p1", ["notion"])
    notion_calls = [c for c in store["calls"] if c[0] == "notion"]
    assert set(notion_calls) == {("notion", "pg-1"), ("notion", "pg-ko"), ("notion", "pg-en")}


def test_remote_error_is_reported_and_blocks_doc_delete(store, monkeypatch):
    def boom(_tid):
        raise RuntimeError("x api down")

    monkeypatch.setattr(base.x, "delete", boom)
    store["post"] = _published_post()
    result = base.delete_post_channels("p1", None, delete_doc=True)
    assert result["channels"]["x"].startswith("error:")
    assert result["channels"]["notion"] == "deleted"
    assert result["docDeleted"] is False
    assert store["doc_deleted"] is False


def test_pending_channel_without_artifact_is_disabled(store):
    post = _published_post()
    post.channels["x"] = ChannelState(enabled=True, status=ChannelStatus.pending)
    store["post"] = post
    result = base.delete_post_channels("p1", ["x"])
    assert store["calls"] == []  # no remote call without an externalId
    assert result["channels"] == {"x": "deleted"}
    assert store["channel_updates"] == [("x", ChannelStatus.skipped)]


def test_delete_endpoint_404(monkeypatch):
    monkeypatch.setattr(base.posts, "get", lambda _id: None)
    assert client.post("/api/posts/nope/delete", json={}).status_code == 404


def test_delete_endpoint_ok(monkeypatch, store):
    store["post"] = _published_post()
    resp = client.post(
        "/api/posts/p1/delete", json={"channels": ["threads"], "deletePost": False}
    )
    assert resp.status_code == 200
    assert resp.json()["channels"] == {"threads": "deleted"}
