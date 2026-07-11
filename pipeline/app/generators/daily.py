"""Daily short-form generation: recent items → one Post per category with
per-channel texts in the languages configured in channelConfigs."""

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
from app.repo import configs, items
from app.utils.logging import get_logger

log = get_logger(__name__)

LOOKBACK_HOURS = 36
MAX_ITEMS = 15

LANG_NAMES = {"ja": "Japanese", "ko": "Korean", "en": "English"}


def _shrink_retry(model: str, system: str, user: str, result: dict, usage: TokenUsage) -> dict:
    """One corrective pass when a channel text exceeds its limit."""
    feedback = (
        "Your previous output exceeded length limits. Regenerate the SAME JSON but "
        f"shorter: x_text must fit 250 weighted chars, threads_text 480 chars.\n"
        f"Previous output: {result}"
    )
    return generate_json(model, system, user + "\n\n" + feedback, usage)


def generate_for_category(category: Category) -> Post | None:
    settings = get_settings()
    cfg_x = configs.channel_config(category.slug, Cadence.daily, Channel.x)
    cfg_th = configs.channel_config(category.slug, Cadence.daily, Channel.threads)
    cfg_no = configs.channel_config(category.slug, Cadence.daily, Channel.notion)
    if not any(c.enabled for c in (cfg_x, cfg_th, cfg_no)):
        return None

    recent = items.recent_for_category(category.slug, LOOKBACK_HOURS, limit=MAX_ITEMS)
    if not recent:
        log.info("no recent items", extra={"fields": {"category": category.slug}})
        return None

    template = configs.prompt_template(category.slug, Cadence.daily)
    if template is None:
        log.warning("no daily prompt template", extra={"fields": {"category": category.slug}})
        return None

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    user_prompt = template.userPromptTemplate.format(
        items=prompts.format_items_for_prompt(recent),
        category=category.name,
        date=today,
        language=LANG_NAMES.get(cfg_no.language, cfg_no.language),
        x_language=LANG_NAMES.get(cfg_x.language, cfg_x.language),
        threads_language=LANG_NAMES.get(cfg_th.language, cfg_th.language),
        notion_language=LANG_NAMES.get(cfg_no.language, cfg_no.language),
    )
    model = template.modelOverride or settings.openai_model_daily
    usage = TokenUsage()
    result = generate_json(model, template.systemPrompt, user_prompt, usage)

    x_text = renderer.strip_urls(str(result.get("x_text", "")))
    threads_text = str(result.get("threads_text", ""))
    if not renderer.fits_x(x_text) or not renderer.fits_threads(threads_text):
        result = _shrink_retry(model, template.systemPrompt, user_prompt, result, usage)
        x_text = renderer.strip_urls(str(result.get("x_text", "")))
        threads_text = str(result.get("threads_text", ""))
    # last resort: hard-trim so the daily run never dies on length
    if not renderer.fits_threads(threads_text):
        threads_text = threads_text[: renderer.THREADS_LIMIT - 1] + "…"

    x_parts = renderer.split_for_x_thread(x_text)

    app = configs.app_settings()
    image_path = ""
    if app.attachImages:
        for it in recent:
            if it.imageRefs:
                image_path = it.imageRefs[0].gcsPath
                break

    post = Post(
        cadence=Cadence.daily,
        categoryId=category.slug,
        status=PostStatus.draft if app.dailyRequireApproval else PostStatus.approved,
        title=str(result.get("notion_title", f"{category.name} — {today}")),
        summary=str(result.get("notion_summary", "")),
        body=str(result.get("notion_summary", "")),
        sourceItemIds=[it.id for it in recent],
        tokenUsage=usage,
        channels={
            "x": ChannelState(
                enabled=cfg_x.enabled, lang=cfg_x.language, text=x_text,
                threadParts=x_parts if len(x_parts) > 1 else [],
                status=ChannelStatus.pending if cfg_x.enabled else ChannelStatus.skipped,
                imageGcsPath=image_path,
            ),
            "threads": ChannelState(
                enabled=cfg_th.enabled, lang=cfg_th.language, text=threads_text,
                status=ChannelStatus.pending if cfg_th.enabled else ChannelStatus.skipped,
                imageGcsPath=image_path,
            ),
            "notion": ChannelState(
                enabled=cfg_no.enabled, lang=cfg_no.language,
                text=str(result.get("notion_summary", "")),
                status=ChannelStatus.pending if cfg_no.enabled else ChannelStatus.skipped,
            ),
        },
    )
    return post
