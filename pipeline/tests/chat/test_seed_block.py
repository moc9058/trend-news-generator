"""Seed injection into the report planner and the short/article generators."""

import pytest

from app.models import Category, ChatSeed, ChatSeedSource, Format, PostStatus
from app.research.prompts import PROMPT_VERSION, SEED_CONTEXT_USER, build_seed_block
from app.research.schemas import ChatSeedContext


def _seed(**kw):
    return ChatSeed(
        threadId="ct_1", messageId="m_1", theme="Diet oversight",
        summary="The Diet debated this in 1988.",
        sources=[ChatSeedSource(url="https://kokkai.ndl.go.jp/txt/1",
                                title="第114回国会", snippet="答弁記録")],
        **kw)


# --------------------------------------------------------------------------- #
# build_seed_block (report)                                                    #
# --------------------------------------------------------------------------- #

def test_no_seed_context_yields_empty_block():
    assert build_seed_block(None) == ""


def test_seed_block_carries_summary_and_sources():
    block = build_seed_block(ChatSeedContext(
        threadId="ct_1", messageId="m_1", summary="prior finding",
        sources=[ChatSeedSource(url="https://a.example/1", title="A", snippet="snip")]))
    assert "prior finding" in block
    assert "https://a.example/1" in block
    assert "A" in block
    assert "snip" in block


def test_seed_block_frames_prior_work_as_unverified():
    """The planner must not treat the chat's conclusion as established."""
    block = build_seed_block(ChatSeedContext(summary="s", sources=[]))
    lowered = block.lower()
    assert "starting point" in lowered
    assert "verify" in lowered
    assert "not as established fact" in lowered


def test_seed_block_handles_empty_sources():
    block = build_seed_block(ChatSeedContext(summary="s", sources=[]))
    assert "(none)" in block


def test_static_seed_text_is_folded_into_prompt_version():
    """SEED_CONTEXT_USER ends in _USER, so the hash covers it by convention."""
    import hashlib
    blob = "".join(v for k, v in sorted(vars(__import__(
        "app.research.prompts", fromlist=["x"])).items())
        if k.endswith(("_SYSTEM", "_USER")) and isinstance(v, str))
    assert SEED_CONTEXT_USER in blob
    assert PROMPT_VERSION == "prompts@" + hashlib.sha256(blob.encode()).hexdigest()[:12]


def test_plan_phase_injects_seed_block(monkeypatch):
    import app.research.llm as llm_mod
    import app.research.phases.plan as plan_mod
    from app.repo import research as repo_mod
    from app.research.budget import Budget
    from app.research.context import RunContext
    from app.research.schemas import BudgetState, ResearchRun

    seen = {}

    def _structured(schema, model, system, user, **kw):
        seen["user"] = user
        return schema.model_validate({"themeClass": "politics_history", "contested": False,
                                      "rqs": [{"id": "rq1", "q": "?", "strategies": ["kokkai"]}]})
    monkeypatch.setattr(plan_mod.llm, "structured", _structured)
    monkeypatch.setattr(llm_mod, "structured", _structured)
    monkeypatch.setattr(repo_mod, "save", lambda run: None)

    run = ResearchRun(id="rr_1", theme="T", budget=BudgetState(),
                      seedContext=ChatSeedContext(summary="chat found X", sources=[]))
    plan_mod.run(RunContext(run=run, budget=Budget(run.budget)))
    assert "chat found X" in seen["user"]


def test_plan_phase_without_seed_is_unchanged(monkeypatch):
    """The default (non-chat) planner prompt must not gain a stray block."""
    import app.research.phases.plan as plan_mod
    from app.repo import research as repo_mod
    from app.research.budget import Budget
    from app.research.context import RunContext
    from app.research.schemas import BudgetState, ResearchRun

    seen = {}

    def _structured(schema, model, system, user, **kw):
        seen["user"] = user
        return schema.model_validate({"themeClass": "politics_history", "contested": False,
                                      "rqs": [{"id": "rq1", "q": "?", "strategies": ["kokkai"]}]})
    monkeypatch.setattr(plan_mod.llm, "structured", _structured)
    monkeypatch.setattr(repo_mod, "save", lambda run: None)

    run = ResearchRun(id="rr_1", theme="T", budget=BudgetState())
    plan_mod.run(RunContext(run=run, budget=Budget(run.budget)))
    assert "PRIOR WORK" not in seen["user"]


def test_seed_context_survives_a_model_dump_roundtrip():
    """repo.save() full-overwrites from model_dump, so the field must round-trip."""
    from app.research.schemas import BudgetState, ResearchRun
    run = ResearchRun(id="rr_1", trigger="chat", budget=BudgetState(),
                      seedContext=ChatSeedContext(threadId="ct_1", summary="s"))
    restored = ResearchRun(**run.model_dump())
    assert restored.seedContext.threadId == "ct_1"


# --------------------------------------------------------------------------- #
# Generators                                                                   #
# --------------------------------------------------------------------------- #

@pytest.fixture
def gen_stubs(monkeypatch):
    from app.models import AppSettings, ChannelConfig, Channel, PromptTemplate
    from app.repo import configs as configs_mod

    state = {"prompts": [], "app": AppSettings(shortRequireApproval=False)}

    monkeypatch.setattr(configs_mod, "channel_config",
                        lambda c, f, ch: ChannelConfig(categoryId=c, format=f, channel=ch,
                                                       enabled=True, language="ja"))
    monkeypatch.setattr(configs_mod, "app_settings", lambda: state["app"])
    # The two formats interpolate different placeholders (short renders all three
    # channel languages; article renders a theme/outline), so the stub mirrors
    # each real template's slots rather than sharing one.
    SHORT_TPL = ("ITEMS:\n{items}\nCAT {category} {date} {language} "
                 "{x_language} {threads_language} {notion_language} {keywords}")
    ARTICLE_TPL = ("ITEMS:\n{items}\nCAT {category} {date} {language} "
                   "THEME {theme}\nOUTLINE {outline}\n"
                   "{x_language} {threads_language} {keywords}")

    monkeypatch.setattr(configs_mod, "prompt_template", lambda c, f: PromptTemplate(
        categoryId=c, format=f, systemPrompt="sys",
        userPromptTemplate=SHORT_TPL if f == Format.short else ARTICLE_TPL,
        outlineSystemPrompt="osys", outlineUserPromptTemplate="OUTLINE:\n{items}"))
    return state


def test_short_seed_forces_draft_even_with_auto_publish_on(gen_stubs, monkeypatch):
    import app.generators.short as short_mod

    monkeypatch.setattr(short_mod, "generate_json",
                        lambda m, s, u, usage: {"x_text": "x", "threads_text": "t",
                                                "notion_title": "T", "notion_summary": "S"})
    monkeypatch.setattr(short_mod.items, "recent_for_category",
                        lambda *a, **kw: pytest.fail("a seeded run must not read the feed"))

    gen_stubs["app"].shortRequireApproval = False   # auto-publish is ON
    post = short_mod.generate_for_category(Category(slug="tech", name="Tech"), seed=_seed())

    assert post.status == PostStatus.draft          # ...and still a draft
    assert post.chatThreadId == "ct_1"
    assert post.chatMessageId == "m_1"


def test_short_without_seed_keeps_auto_publish(gen_stubs, monkeypatch):
    """The scheduled path's behaviour must be untouched."""
    import app.generators.short as short_mod
    from app.models import Item

    monkeypatch.setattr(short_mod, "generate_json",
                        lambda m, s, u, usage: {"x_text": "x", "threads_text": "t",
                                                "notion_title": "T", "notion_summary": "S"})
    monkeypatch.setattr(short_mod.items, "recent_for_category", lambda *a, **kw: [
        Item(id="i1", categoryId="tech", title="Item", canonicalUrl="https://a/1")])

    gen_stubs["app"].shortRequireApproval = False
    post = short_mod.generate_for_category(Category(slug="tech", name="Tech"))
    assert post.status == PostStatus.approved


def test_short_seed_material_reaches_the_prompt(gen_stubs, monkeypatch):
    import app.generators.short as short_mod
    seen = {}

    def _gen(model, system, user, usage):
        seen["user"] = user
        return {"x_text": "x", "threads_text": "t", "notion_title": "T", "notion_summary": "S"}
    monkeypatch.setattr(short_mod, "generate_json", _gen)

    short_mod.generate_for_category(Category(slug="tech", name="Tech"), seed=_seed())
    assert "The Diet debated this in 1988." in seen["user"]
    assert "https://kokkai.ndl.go.jp/txt/1" in seen["user"]
    assert "Diet oversight" in seen["user"]
    assert "research chat" in seen["user"]          # the seed_block instruction


def test_longform_seed_pins_theme_over_stage1_guess(gen_stubs, monkeypatch):
    import app.generators.longform as lf_mod
    from app.models import Item

    calls = []

    def _gen(model, system, user, usage):
        calls.append(user)
        if len(calls) == 1:
            return {"theme": "stage-1 guess", "outline": ["a"], "selected_item_ids": []}
        return {"title": "T", "summary": "S", "body": "B", "teasers": {}}
    monkeypatch.setattr(lf_mod, "generate_json", _gen)
    monkeypatch.setattr(lf_mod.items, "recent_for_category", lambda *a, **kw: [
        Item(id="i1", categoryId="tech", title="Item", canonicalUrl="https://a/1")])
    monkeypatch.setattr(lf_mod.items, "get_many", lambda ids: [])

    post = lf_mod.generate_for_category(
        Category(slug="tech", name="Tech"), Format.article, seed=_seed())

    assert "Diet oversight" in calls[1]        # the seed theme, not "stage-1 guess"
    assert post.status == PostStatus.draft
    assert post.chatThreadId == "ct_1"


def test_longform_seed_bypasses_the_thin_feed_floor(gen_stubs, monkeypatch):
    """Fewer than 3 items aborts a scheduled run; a seeded one has its own substance."""
    import app.generators.longform as lf_mod

    monkeypatch.setattr(lf_mod, "generate_json", lambda m, s, u, usage: {
        "theme": "t", "outline": [], "selected_item_ids": [],
        "title": "T", "summary": "S", "body": "B", "teasers": {}})
    monkeypatch.setattr(lf_mod.items, "recent_for_category", lambda *a, **kw: [])
    monkeypatch.setattr(lf_mod.items, "get_many", lambda ids: [])

    assert lf_mod.generate_for_category(
        Category(slug="tech", name="Tech"), Format.article) is None
    assert lf_mod.generate_for_category(
        Category(slug="tech", name="Tech"), Format.article, seed=_seed()) is not None
