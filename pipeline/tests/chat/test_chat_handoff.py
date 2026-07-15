"""POST /api/chat/handoff: report → queued run, short/article → draft post.

The invariant under test: this endpoint never publishes anything.
"""

import pytest
from fastapi.testclient import TestClient

import app.chat.api as api_mod
from app.chat.schemas import ChatMessage, ChatMessageStatus, ChatSource, ChatThread
from app.models import Category, PostStatus


class _Repo:
    def __init__(self):
        self.threads = {"ct_1": ChatThread(id="ct_1", requestedBy="me@example.com")}
        self.messages = {
            "m_ok": ChatMessage(
                id="m_ok", role="assistant", mode="research", depth="quick",
                content="The Diet debated this in 1988. [1]",
                status=ChatMessageStatus.complete.value,
                sources=[ChatSource(n=1, url="https://kokkai.ndl.go.jp/txt/1",
                                    title="第114回国会", tier="primary", score=85)]),
            "m_streaming": ChatMessage(id="m_streaming", role="assistant",
                                       content="half", status="streaming"),
            "m_user": ChatMessage(id="m_user", role="user", content="q",
                                  status="complete"),
        }
        self.handoffs = []
        self.usage = []

    def get_thread(self, tid):
        return self.threads.get(tid)

    def get_message(self, tid, mid):
        return self.messages.get(mid)

    def append_handoff(self, tid, mid, h):
        self.handoffs.append((tid, mid, h))

    def recent_history(self, tid, limit):
        return [{"role": "user", "content": "tell me about the Diet"}]

    def add_usage(self, cost, month="", messages=1):
        self.usage.append(cost)


@pytest.fixture
def repo(monkeypatch):
    r = _Repo()
    monkeypatch.setattr(api_mod, "chat_repo", r)
    return r


@pytest.fixture
def stubs(monkeypatch):
    """Stub the collaborators the handoff reaches into."""
    import app.repo.configs as configs_mod
    import app.repo.posts as posts_mod
    import app.repo.research as research_mod
    import app.main as main_mod

    state = {"runs": [], "posts": [], "triggered": [], "seeds": {}}

    monkeypatch.setattr(configs_mod, "category",
                        lambda slug: Category(slug=slug, name="Tech") if slug == "tech" else None)

    def _create_run(run):
        run.id = "rr_1"
        state["runs"].append(run)
        return "rr_1"
    monkeypatch.setattr(research_mod, "create", _create_run)
    monkeypatch.setattr(main_mod, "_trigger_job", lambda name: state["triggered"].append(name))

    def _create_post(post):
        state["posts"].append(post)
        return "post_1"
    monkeypatch.setattr(posts_mod, "create", _create_post)

    import app.generators.longform as longform_mod
    import app.generators.short as short_mod
    from app.models import Format, Post

    def _fake_short(category, seed=None):
        state["seeds"]["short"] = seed
        return Post(format=Format.short, categoryId=category.slug,
                    status=PostStatus.draft, title="t",
                    chatThreadId=seed.threadId if seed else "",
                    chatMessageId=seed.messageId if seed else "")

    def _fake_longform(category, post_format, seed=None):
        state["seeds"]["article"] = seed
        return Post(format=post_format, categoryId=category.slug,
                    status=PostStatus.draft, title="t",
                    chatThreadId=seed.threadId if seed else "",
                    chatMessageId=seed.messageId if seed else "")

    monkeypatch.setattr(short_mod, "generate_for_category", _fake_short)
    monkeypatch.setattr(longform_mod, "generate_for_category", _fake_longform)
    return state


@pytest.fixture
def client(repo, stubs):
    from app.main import app
    return TestClient(app)


def _post(client, **kw):
    body = {"threadId": "ct_1", "messageId": "m_ok", "format": "short",
            "categoryId": "tech", **kw}
    return client.post("/api/chat/handoff", json=body)


# --------------------------------------------------------------------------- #

def test_report_handoff_queues_run_with_seed_context(client, stubs):
    resp = _post(client, format="report", theme="Diet oversight", categoryId=None)
    assert resp.status_code == 200
    assert resp.json() == {"ok": True, "kind": "research_run", "refId": "rr_1"}

    run = stubs["runs"][0]
    assert run.trigger == "chat"
    assert run.theme == "Diet oversight"
    assert run.requestedBy == "me@example.com"
    assert run.status == "queued"
    assert run.seedContext.threadId == "ct_1"
    assert run.seedContext.messageId == "m_ok"
    assert "1988" in run.seedContext.summary
    assert run.seedContext.sources[0].url == "https://kokkai.ndl.go.jp/txt/1"
    assert stubs["triggered"] == ["generate_report"]


def test_report_handoff_distils_theme_when_absent(client, stubs, monkeypatch):
    import app.research.llm as llm_mod

    def _structured(schema, model, system, user, **kw):
        assert "tell me about the Diet" in user
        return schema.model_validate({"theme": "distilled theme",
                                      "questions": ["rq1", "rq2"]})
    monkeypatch.setattr(api_mod.llm, "structured", _structured)
    monkeypatch.setattr(llm_mod, "structured", _structured)

    _post(client, format="report", theme=None, categoryId=None)
    run = stubs["runs"][0]
    assert run.theme == "distilled theme"
    assert run.questions == ["rq1", "rq2"]


def test_failed_trigger_still_returns_ok_and_leaves_run_queued(client, stubs, monkeypatch):
    import app.main as main_mod
    monkeypatch.setattr(main_mod, "_trigger_job",
                        lambda name: (_ for _ in ()).throw(RuntimeError("no perms")))
    resp = _post(client, format="report", theme="T", categoryId=None)
    assert resp.status_code == 200
    assert stubs["runs"][0].status == "queued"


def test_short_handoff_creates_draft_with_backrefs(client, stubs):
    resp = _post(client, format="short")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True, "kind": "post", "refId": "post_1"}

    post = stubs["posts"][0]
    assert post.status == PostStatus.draft
    assert post.chatThreadId == "ct_1"
    assert post.chatMessageId == "m_ok"

    seed = stubs["seeds"]["short"]
    assert seed.summary == "The Diet debated this in 1988. [1]"
    assert seed.sources[0].title == "第114回国会"


def test_article_handoff_uses_longform(client, stubs):
    resp = _post(client, format="article")
    assert resp.status_code == 200
    assert stubs["posts"][0].format.value == "article"
    assert stubs["seeds"]["article"].threadId == "ct_1"


def test_handoff_records_backreference_on_the_message(client, repo):
    _post(client, format="short")
    tid, mid, h = repo.handoffs[0]
    assert (tid, mid) == ("ct_1", "m_ok")
    assert (h.format, h.refId) == ("short", "post_1")
    assert h.at is not None


def test_incomplete_message_is_409(client):
    assert _post(client, messageId="m_streaming").status_code == 409


def test_user_message_cannot_be_handed_off(client):
    assert _post(client, messageId="m_user").status_code == 409


def test_unknown_thread_and_message_are_404(client):
    assert _post(client, threadId="ct_nope").status_code == 404
    assert _post(client, messageId="m_nope").status_code == 404


def test_unknown_category_is_400(client):
    assert _post(client, categoryId="nope").status_code == 400


def test_unknown_format_is_400(client):
    assert _post(client, format="podcast").status_code == 400
