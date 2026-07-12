"""Focus-keyword injection (collection + generation) and the draft-cleanup job."""

from app.collectors.gemini_grounded import GeminiGroundedCollector
from app.generators import prompts
from app.models import Cadence, Post, PostStatus, Source, SourceType

# ---------- keyword focus helpers ----------


def test_keyword_focus_line_empty():
    assert prompts.keyword_focus_line([]) == ""
    assert prompts.keyword_focus_line(["  ", ""]) == ""


def test_keyword_focus_line_lists_keywords():
    line = prompts.keyword_focus_line(["semiconductors", "quantum"])
    assert "semiconductors" in line and "quantum" in line
    assert "still include" in line  # the 重視 (not 限定) policy


def test_apply_keywords_appends_when_no_placeholder():
    out = prompts.apply_keywords("BODY", "user template {items}", ["AI"])
    assert out.startswith("BODY")
    assert "AI" in out and "FOCUS KEYWORDS" in out


def test_apply_keywords_skips_when_placeholder_present():
    tpl = "focus on {keywords}\n{items}"
    out = prompts.apply_keywords("already has keywords", tpl, ["AI"])
    assert out == "already has keywords"  # no double emphasis


def test_apply_keywords_noop_without_keywords():
    assert prompts.apply_keywords("BODY", "{items}", []) == "BODY"


# ---------- gemini grounded collection steering ----------


class _FakeModels:
    def __init__(self):
        self.last_contents = None

    def generate_content(self, model, contents, config):
        self.last_contents = contents

        class _R:
            text = '[{"title":"t","url":"https://example.com/a","summary":"s"}]'
            candidates: list = []

        return _R()


class _FakeClient:
    def __init__(self):
        self.models = _FakeModels()


def test_gemini_grounded_injects_focus_keywords():
    client = _FakeClient()
    collector = GeminiGroundedCollector(client=client)
    src = Source(id="s", categoryId="science-technology",
                 type=SourceType.gemini_grounded, query="tech news")
    items = collector.collect(src, ["semiconductors", "quantum computing"])
    assert "semiconductors" in client.models.last_contents
    assert "quantum computing" in client.models.last_contents
    assert len(items) == 1


def test_gemini_grounded_without_keywords_omits_focus_clause():
    client = _FakeClient()
    collector = GeminiGroundedCollector(client=client)
    src = Source(id="s", categoryId="x", type=SourceType.gemini_grounded, query="tech news")
    collector.collect(src, [])
    assert "extra weight" not in client.models.last_contents


# ---------- cleanup_drafts job ----------


def test_cleanup_drafts_deletes_old_and_records_count(monkeypatch):
    import app.jobs.cleanup_drafts as cd

    stale = [
        Post(id="p1", cadence=Cadence.weekly, categoryId="x", status=PostStatus.draft),
        Post(id="p2", cadence=Cadence.monthly, categoryId="y", status=PostStatus.draft),
    ]
    deleted: list[str] = []
    captured: dict = {}
    monkeypatch.setattr(cd.posts, "old_drafts", lambda days: stale)
    monkeypatch.setattr(cd.posts, "delete", lambda pid: deleted.append(pid))
    monkeypatch.setattr(cd.runs, "start", lambda name: "run1")
    monkeypatch.setattr(cd.runs, "finish", lambda rid, run: captured.update(run=run))

    cd.main()

    assert deleted == ["p1", "p2"]
    assert captured["run"].stats.deleted == 2
    assert captured["run"].ok is True
