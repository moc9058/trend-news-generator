"""Article two-stage long-form generation (was the weekly/monthly path).

Stage 1 (openai_model_daily): theme + outline + 15-25 item selection from the period's
items. Stage 2 (openai_model_longform): full article from the selected items' full text, plus
per-channel teasers. Saved as status=draft — publishing happens only after
approval in the admin UI. (The old monthly deep-dive path is replaced by the
Research Agent report system; see docs/tech-report/05-detailed-design/10.)
"""

from datetime import datetime, timezone

from app.config import get_settings
from app.generators import prompts
from app.generators.openai_client import generate_json
from app.models import (
    Category,
    Channel,
    ChannelState,
    ChannelStatus,
    Format,
    Post,
    PostStatus,
    TokenUsage,
)
from app.publishers import renderer
from app.repo import configs, items
from app.utils.logging import get_logger

log = get_logger(__name__)

LOOKBACK = {Format.article: 7 * 24}
MAX_CANDIDATES = 120
MAX_SELECTED = 25
LANG_NAMES = {"ja": "Japanese", "ko": "Korean", "en": "English"}


def generate_for_category(category: Category, post_format: Format) -> Post | None:
    settings = get_settings()
    template = configs.prompt_template(category.slug, post_format)
    if template is None:
        log.warning("no prompt template", extra={"fields": {"category": category.slug, "format": post_format.value}})
        return None

    candidates = items.recent_for_category(
        category.slug, LOOKBACK[post_format], limit=MAX_CANDIDATES
    )
    if len(candidates) < 3:
        log.info("too few items", extra={"fields": {"category": category.slug, "n": len(candidates)}})
        return None

    cfg_x = configs.channel_config(category.slug, post_format, Channel.x)
    cfg_th = configs.channel_config(category.slug, post_format, Channel.threads)
    cfg_no = configs.channel_config(category.slug, post_format, Channel.notion)
    lang = LANG_NAMES.get(cfg_no.language, cfg_no.language)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    usage = TokenUsage()

    # ---- stage 1: selection & outline (cheap model) ----
    items_block = prompts.format_items_for_prompt(candidates, include_ids=True)

    keywords_str = ", ".join(template.focusKeywords)
    outline_tpl = template.outlineUserPromptTemplate or "{items}"
    outline_user = outline_tpl.format(
        items=items_block, category=category.name, date=today, language=lang,
        keywords=keywords_str,
    )
    outline_user = prompts.apply_keywords(outline_user, outline_tpl, template.focusKeywords)
    outline_user = prompts.apply_custom_instructions(outline_user, template.customInstructions)
    outline = generate_json(
        settings.openai_model_daily,
        template.outlineSystemPrompt or prompts.ARTICLE_OUTLINE_SYSTEM,
        outline_user,
        usage,
    )
    selected_ids = [
        i for i in outline.get("selected_item_ids", []) if isinstance(i, str)
    ][:MAX_SELECTED]
    selected = items.get_many(selected_ids)
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
        keywords=keywords_str,
    )
    article_user = prompts.apply_keywords(
        article_user, template.userPromptTemplate, template.focusKeywords
    )
    article_user = prompts.apply_custom_instructions(article_user, template.customInstructions)
    model = template.modelOverride or settings.openai_model_longform
    article = generate_json(model, template.systemPrompt, article_user, usage)

    teasers = article.get("teasers") or {}
    x_teaser = renderer.strip_urls(str(teasers.get("x", "")))
    threads_teaser = str(teasers.get("threads", ""))

    post = Post(
        format=post_format,
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
