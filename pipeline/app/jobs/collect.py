"""Daily collection job (06:00 JST).

Per enabled category: run every enabled source through its collector, normalize
URLs, transactionally create items (URL-hash doc ID → exact dedup), drop
near-duplicate titles seen within 7 days, store og:image to GCS. A failing
source is logged and skipped — one bad feed never kills the run.
"""

from datetime import datetime, timezone

import httpx

from app.collectors.base import RawItem
from app.collectors.enrich import fetch_image, fetch_page
from app.collectors.gemini_grounded import GeminiGroundedCollector
from app.collectors.ieee_xplore import IeeeXploreCollector
from app.collectors.rss import RssCollector
from app.models import ImageRef, Item, Run, Source, SourceType
from app.normalize import canonicalize_url, item_doc_id, title_norm_hash
from app.repo import configs, items, runs
from app.utils import gcs
from app.utils.logging import get_logger

log = get_logger(__name__)


def _persist(raw: RawItem, source: Source, http: httpx.Client, stats) -> None:
    canonical = canonicalize_url(raw.url)
    doc_id = item_doc_id(canonical)
    t_hash = title_norm_hash(raw.title)

    if items.title_hash_seen_since(source.categoryId, t_hash, days=7):
        stats.deduped += 1
        return

    image_url, content_text = raw.imageUrl, raw.contentText
    if not image_url or not content_text:
        og_image, page_text = fetch_page(canonical, http)
        image_url = image_url or og_image
        content_text = content_text or page_text

    image_refs: list[ImageRef] = []
    if image_url:
        fetched = fetch_image(image_url, http)
        if fetched:
            data, mime = fetched
            ext = mime.split("/")[-1]
            path = f"items/{doc_id}/og.{ext}"
            gcs.upload_bytes(path, data, mime)
            image_refs.append(ImageRef(gcsPath=path, mime=mime))

    item = Item(
        id=doc_id,
        categoryId=source.categoryId,
        title=raw.title,
        canonicalUrl=canonical,
        publishedAt=raw.publishedAt,
        collectedAt=datetime.now(timezone.utc),
        summary=raw.summary,
        contentText=content_text,
        titleNormHash=t_hash,
        sourceId=source.id,
        imageRefs=image_refs,
        groundingCitations=raw.groundingCitations,
    )
    if items.create_if_absent(item):
        stats.collected += 1
    else:
        stats.deduped += 1


def main() -> None:
    run_id = runs.start("collect")
    run = Run(jobType="collect")
    collectors = {
        SourceType.rss: RssCollector(),
        SourceType.gemini_grounded: GeminiGroundedCollector(),
        SourceType.ieee_xplore: IeeeXploreCollector(),
    }
    http = httpx.Client(
        timeout=20, follow_redirects=True,
        headers={"User-Agent": "trend-news-generator/1.0"},
    )

    for category in configs.enabled_categories():
        focus_keywords = configs.category_focus_keywords(category.slug)
        for source in configs.enabled_sources(category.slug):
            collector = collectors[source.type]
            try:
                raw_items = collector.collect(source, focus_keywords)
            except Exception as exc:
                msg = f"source {source.id or source.url or source.query}: {exc}"
                log.warning("collector failed", extra={"fields": {"error": msg}})
                run.errors.append(msg)
                continue
            for raw in raw_items:
                try:
                    _persist(raw, source, http, run.stats)
                except Exception as exc:
                    run.errors.append(f"persist {raw.url}: {exc}")

    run.ok = not run.errors
    runs.finish(run_id, run)
    log.info(
        "collect finished",
        extra={"fields": {"collected": run.stats.collected, "deduped": run.stats.deduped,
                          "errors": len(run.errors)}},
    )


if __name__ == "__main__":
    main()
