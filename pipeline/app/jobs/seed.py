"""One-shot seed job: initial categories, RSS + Gemini sources, default prompt
templates, channel configs (x=ja, threads=ko, notion=en) and app settings.
Idempotent: existing documents are left untouched (merge=False create-only)."""

from app.generators.prompts import DEFAULTS
from app.repo.client import db
from app.utils.logging import get_logger

log = get_logger(__name__)

CATEGORIES = [
    {"slug": "business-economics", "name": "Business & Economics", "sortOrder": 0,
     "searchHints": ["macroeconomy", "markets", "central banks", "major corporate news"]},
    {"slug": "science-technology", "name": "Science & Technology", "sortOrder": 1,
     "searchHints": ["AI", "semiconductors", "space", "biotech", "breakthrough research"]},
    {"slug": "geopolitics-history", "name": "Geopolitics & History", "sortOrder": 2,
     "searchHints": ["international relations", "conflicts", "diplomacy", "elections"]},
]

SOURCES = [
    # Business & Economics
    {"id": "bizecon-gemini", "categoryId": "business-economics", "type": "gemini_grounded",
     "query": "global business, economics, markets and central bank news"},
    {"id": "bizecon-reuters-biz", "categoryId": "business-economics", "type": "rss",
     "url": "https://feeds.reuters.com/reuters/businessNews"},
    {"id": "bizecon-nikkei", "categoryId": "business-economics", "type": "rss",
     "url": "https://www.nikkei.com/rss/index.rdf"},
    # Science & Technology
    {"id": "scitech-gemini", "categoryId": "science-technology", "type": "gemini_grounded",
     "query": "major science and technology news: AI, semiconductors, space, biotech"},
    {"id": "scitech-arstechnica", "categoryId": "science-technology", "type": "rss",
     "url": "https://feeds.arstechnica.com/arstechnica/index"},
    {"id": "scitech-mit-tr", "categoryId": "science-technology", "type": "rss",
     "url": "https://www.technologyreview.com/feed/"},
    # Academic sources, disabled by default — enable in the admin UI once wanted.
    # arXiv's API returns Atom, so it works through the plain rss source type;
    # tune the search_query to taste.
    {"id": "scitech-arxiv-csai", "categoryId": "science-technology", "type": "rss",
     "url": "https://export.arxiv.org/api/query?search_query=cat:cs.AI&sortBy=submittedDate&sortOrder=descending&max_results=10",
     "enabled": False},
    # Requires the free ieee-api-key secret (developer.ieee.org).
    {"id": "scitech-ieee", "categoryId": "science-technology", "type": "ieee_xplore",
     "query": "artificial intelligence OR semiconductor", "enabled": False},
    # Geopolitics & History
    {"id": "geo-gemini", "categoryId": "geopolitics-history", "type": "gemini_grounded",
     "query": "major geopolitics and international relations news"},
    {"id": "geo-reuters-world", "categoryId": "geopolitics-history", "type": "rss",
     "url": "https://feeds.reuters.com/Reuters/worldNews"},
]

CHANNEL_LANGUAGES = {"x": "ja", "threads": "ko", "notion": "en"}


def _create_if_absent(collection: str, doc_id: str, data: dict) -> bool:
    ref = db().collection(collection).document(doc_id)
    if ref.get().exists:
        return False
    ref.set(data)
    return True


def main() -> None:
    created = 0
    for cat in CATEGORIES:
        data = {**cat, "enabled": True}
        slug = data.pop("slug")
        created += _create_if_absent("categories", slug, data)

    for src in SOURCES:
        data = {"enabled": True, "etag": "", "lastModified": "",
                "url": src.get("url", ""), "query": src.get("query", ""), **src}
        source_id = data.pop("id")
        created += _create_if_absent("sources", source_id, data)

    for cat in CATEGORIES:
        for post_format, defaults in DEFAULTS.items():
            doc_id = f"{cat['slug']}_{post_format}"
            created += _create_if_absent("promptTemplates", doc_id, {
                "categoryId": cat["slug"],
                "format": post_format,
                "systemPrompt": defaults["systemPrompt"],
                "userPromptTemplate": defaults["userPromptTemplate"],
                "outlineSystemPrompt": defaults.get("outlineSystemPrompt", ""),
                "outlineUserPromptTemplate": defaults.get("outlineUserPromptTemplate", ""),
                "modelOverride": "",
                "focusKeywords": [],
                "enabled": True,
            })
            for channel, language in CHANNEL_LANGUAGES.items():
                created += _create_if_absent(
                    "channelConfigs", f"{cat['slug']}_{post_format}_{channel}",
                    {"categoryId": cat["slug"], "format": post_format, "channel": channel,
                     "enabled": True, "language": language},
                )

    created += _create_if_absent("settings", "app", {
        "timezone": "Asia/Tokyo",
        "shortRequireApproval": False,
        "xAllowUrlOnShort": False,
        "attachImages": True,
    })
    created += _create_if_absent("settings", "notion", {"databaseId": ""})
    created += _create_if_absent("settings", "channelHealth", {})

    log.info("seed finished", extra={"fields": {"created": created}})


if __name__ == "__main__":
    main()
