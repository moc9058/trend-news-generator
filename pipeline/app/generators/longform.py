"""Weekly/monthly two-stage long-form generation.

Stage 1 (gpt-5.4-mini): theme + outline + 15-25 item selection from the period's
items (monthly additionally sees the month's weekly article summaries —
hierarchical accumulation). Stage 2 (gpt-5.5): full article from the selected
items' full text, plus per-channel teasers. Saved as status=draft — publishing
happens only after approval in the admin UI.
"""

from datetime import datetime, timezone

from app.config import get_settings
from app.generators import prompts
from app.generators.openai_client import generate_json
from app.models import (
    Cadence,
    Category,
    Channel,
    ChannelState,
    ChannelStatus,
    Post,
    PostStatus,
    TokenUsage,
)
from app.publishers import renderer
from app.repo import configs, items, posts
from app.utils.logging import get_logger

log = get_logger(__name__)

LOOKBACK = {Cadence.weekly: 7 * 24, Cadence.monthly: 30 * 24}
MAX_CANDIDATES = 120
MAX_SELECTED = 25
LANG_NAMES = {"ja": "Japanese", "ko": "Korean", "en": "English"}


def _weekly_summaries_for_month(category_id: str) -> str:
    """Summaries of this month's weekly posts, fed into the monthly stage 1."""
    recent = posts.recent_by_cadence(Cadence.weekly.value, limit=8)
    now = datetime.now(timezone.utc)
    lines = []
    for p in recent:
        if p.categoryId != category_id or not p.createdAt:
            continue
        created = p.createdAt if p.createdAt.tzinfo else p.createdAt.replace(tzinfo=timezone.utc)
        if (now - created).days <= 31:
            lines.append(f"[weekly:{p.id}] {p.title}\n  {p.summary}")
    return "\n".join(lines)


def generate_for_category(category: Category, cadence: Cadence) -> Post | None:
    settings = get_settings()
    template = configs.prompt_template(category.slug, cadence)
    if template is None:
        log.warning("no prompt template", extra={"fields": {"category": category.slug, "cadence": cadence.value}})
        return None

    candidates = items.recent_for_category(
        category.slug, LOOKBACK[cadence], limit=MAX_CANDIDATES
    )
    if len(candidates) < 3:
        log.info("too few items", extra={"fields": {"category": category.slug, "n": len(candidates)}})
        return None

    cfg_x = configs.channel_config(category.slug, cadence, Channel.x)
    cfg_th = configs.channel_config(category.slug, cadence, Channel.threads)
    cfg_no = configs.channel_config(category.slug, cadence, Channel.notion)
    lang = LANG_NAMES.get(cfg_no.language, cfg_no.language)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    usage = TokenUsage()

    # ---- stage 1: selection & outline (cheap model) ----
    items_block = prompts.format_items_for_prompt(candidates, include_ids=True)
    if cadence == Cadence.monthly:
        weekly_block = _weekly_summaries_for_month(category.slug)
        if weekly_block:
            items_block += "\n\nThis month's weekly articles:\n" + weekly_block

    outline_user = (template.outlineUserPromptTemplate or "{items}").format(
        items=items_block, category=category.name, date=today, language=lang,
    )
    outline = generate_json(
        settings.openai_model_daily,
        template.outlineSystemPrompt or prompts.WEEKLY_OUTLINE_SYSTEM,
        outline_user,
        usage,
    )
    selected_ids = [
        i for i in outline.get("selected_item_ids", []) if isinstance(i, str)
    ][:MAX_SELECTED]
    selected = items.get_many([i for i in selected_ids if not i.startswith("weekly:")])
    if not selected:
        selected = candidates[:MAX_SELECTED]

    # ---- stage 2: full article (frontier model) ----
    article_user = template.userPromptTemplate.format(
        items=prompts.format_items_for_prompt(selected, include_ids=True, max_content=4000),
        category=category.name,
        date=today,
        language=lang,
        theme=outline.get("theme", ""),
        outline="\n".join(f"- {s}" for s in outline.get("outline", [])),
        x_language=LANG_NAMES.get(cfg_x.language, cfg_x.language),
        threads_language=LANG_NAMES.get(cfg_th.language, cfg_th.language),
    )
    model = template.modelOverride or settings.openai_model_longform
    article = generate_json(model, template.systemPrompt, article_user, usage)

    teasers = article.get("teasers") or {}
    x_teaser = renderer.strip_urls(str(teasers.get("x", "")))
    threads_teaser = str(teasers.get("threads", ""))

    post = Post(
        cadence=cadence,
        categoryId=category.slug,
        status=PostStatus.draft,
        title=str(article.get("title", outline.get("title", ""))),
        summary=str(article.get("summary", "")),
        body=str(article.get("body", "")),
        sourceItemIds=[it.id for it in selected],
        tokenUsage=usage,
        channels={
            # X/Threads teasers get the Notion public URL appended at publish time
            "x": ChannelState(
                enabled=cfg_x.enabled, lang=cfg_x.language, text=x_teaser,
                status=ChannelStatus.pending if cfg_x.enabled else ChannelStatus.skipped,
            ),
            "threads": ChannelState(
                enabled=cfg_th.enabled, lang=cfg_th.language, text=threads_teaser,
                status=ChannelStatus.pending if cfg_th.enabled else ChannelStatus.skipped,
            ),
            "notion": ChannelState(
                enabled=cfg_no.enabled, lang=cfg_no.language, text="",
                status=ChannelStatus.pending if cfg_no.enabled else ChannelStatus.skipped,
            ),
        },
    )
    return post
