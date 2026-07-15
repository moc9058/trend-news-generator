"""Default prompt templates seeded into Firestore (editable in the admin UI).

Contract: templates instruct on CONTENT only. Output languages come from
channelConfigs and are injected as {language} / per-channel language fields.
Placeholders available to userPromptTemplate: {items} {category} {date} {language}.
"""

SHORT_SYSTEM = """You are a sharp, trustworthy news curator writing short social posts.
Hard rules:
- Use ONLY facts present in the provided source items. Never invent facts, numbers, or quotes.
- No hashtags spam (max 2), no emojis walls (max 2), no clickbait.
- If the items are thin or contradictory, write a cautious roundup rather than a bold claim.
Return strictly the JSON object requested, nothing else."""

SHORT_USER = """Today is {date}. Category: {category}.

Source items (title / summary / url):
{items}

Write a short trend brief for this category as JSON:
{{
  "x_text": "post for X in {x_language}, <= 250 chars, no URLs",
  "threads_text": "post for Threads in {threads_language}, <= 480 chars, no URLs",
  "notion_title": "concise page title in {notion_language}",
  "notion_summary": "5-8 sentence digest in {notion_language}, markdown, cite item titles inline"
}}
Pick the 2-4 most significant stories; synthesize, don't enumerate everything."""

ARTICLE_OUTLINE_SYSTEM = """You are a senior editor planning a weekly analysis piece
(The Economist / FT standard). Select and structure only — do not write the article.
Use ONLY the provided items. Return strictly the requested JSON."""

ARTICLE_OUTLINE_USER = """Week ending {date}. Category: {category}.

Candidate items (id / title / summary):
{items}

Return JSON:
{{
  "theme": "the single most consequential thread of the week",
  "title": "working title in {language}",
  "outline": ["section 1 focus", "section 2 focus", "..."],
  "selected_item_ids": ["15-25 ids, the strongest evidence for this theme"]
}}"""

ARTICLE_SYSTEM = """You are a staff writer at a top-tier publication
(The Economist / Financial Times caliber). Write with analytical depth, concrete
evidence, and restraint. Use ONLY facts from the provided sources; attribute
claims to sources naturally in the text. Return strictly the requested JSON."""

ARTICLE_USER = """Week ending {date}. Category: {category}. Theme: {theme}

Outline:
{outline}

Full source material:
{items}

Return JSON:
{{
  "title": "final headline in {language}",
  "body": "1200-1800 word article in {language}, markdown with ## sections, ending with a short 'Sources' list of the URLs actually used",
  "summary": "3-4 sentence abstract in {language}",
  "teasers": {{"x": "teaser in {x_language} <= 200 chars (a URL will be appended)", "threads": "teaser in {threads_language} <= 400 chars (a URL will be appended)"}}
}}"""

# Style/tone defaults for the report format. The Research Agent (P3-P5) owns the
# report logic; promptTemplates/{cat}_report only steers voice and tone (§6.5).
REPORT_OUTLINE_SYSTEM = ARTICLE_OUTLINE_SYSTEM.replace("weekly analysis piece", "deep-dive research report")

REPORT_OUTLINE_USER = """Category: {category}, as of {date}.

Candidate items (id / title / summary):
{items}

Return JSON:
{{
  "theme": "the defining development and its structural implications",
  "title": "working title in {language}",
  "outline": ["6-10 report sections, from context to outlook"],
  "selected_item_ids": ["15-25 ids"]
}}"""

REPORT_SYSTEM = """You are a research analyst writing a deep-dive research report
(think-tank / institutional research caliber). Rigorous, structured,
evidence-first; distinguish facts from interpretation. Use ONLY the provided
sources. Return strictly the requested JSON."""

REPORT_USER = ARTICLE_USER.replace(
    "1200-1800 word article", "3000-5000 word report"
)

DEFAULTS = {
    "short": {"systemPrompt": SHORT_SYSTEM, "userPromptTemplate": SHORT_USER},
    "article": {
        "systemPrompt": ARTICLE_SYSTEM,
        "userPromptTemplate": ARTICLE_USER,
        "outlineSystemPrompt": ARTICLE_OUTLINE_SYSTEM,
        "outlineUserPromptTemplate": ARTICLE_OUTLINE_USER,
    },
    "report": {
        "systemPrompt": REPORT_SYSTEM,
        "userPromptTemplate": REPORT_USER,
        "outlineSystemPrompt": REPORT_OUTLINE_SYSTEM,
        "outlineUserPromptTemplate": REPORT_OUTLINE_USER,
    },
}


def keyword_focus_line(keywords: list[str]) -> str:
    """Instruction that makes the model prioritise the focus keywords (but still
    cover the category's major developments — the '重視' policy, not '限定')."""
    kw = ", ".join(k for k in keywords if k.strip())
    if not kw:
        return ""
    return (
        f"\n\nFOCUS KEYWORDS — give extra weight to stories about: {kw}. "
        "Prioritise these topics, but still include the category's most important "
        "developments even when unrelated to the keywords."
    )


def custom_instructions_block(instructions: str) -> str:
    """Standing owner requests, verbatim. They may arrive in Korean, Japanese or
    English (or a mix) — the model must honour them regardless of language, and
    they must never override the output-language rules set by channelConfigs."""
    text = (instructions or "").strip()
    if not text:
        return ""
    return (
        "\n\nOWNER INSTRUCTIONS — the site owner set the following standing requests "
        "for this category. They may be written in Korean, Japanese, or English; "
        "follow them regardless of the language they are written in. They refine "
        "topic selection, emphasis, and style, but they NEVER change the output "
        "language(s) requested above.\n"
        f"<owner_instructions>\n{text}\n</owner_instructions>"
    )


def apply_custom_instructions(user_prompt: str, instructions: str) -> str:
    return user_prompt + custom_instructions_block(instructions)


def apply_keywords(user_prompt: str, template_text: str, keywords: list[str]) -> str:
    """Append the keyword-focus line unless the template already places {keywords}
    itself (avoids double emphasis)."""
    if not keywords or "{keywords}" in template_text:
        return user_prompt
    return user_prompt + keyword_focus_line(keywords)


def format_items_for_prompt(items, include_ids: bool = False, max_content: int = 0) -> str:
    lines = []
    for it in items:
        prefix = f"[{it.id}] " if include_ids else "- "
        line = f"{prefix}{it.title}\n  {it.summary or it.contentText[:300]}\n  {it.canonicalUrl}"
        if max_content and it.contentText:
            line += f"\n  FULL TEXT: {it.contentText[:max_content]}"
        lines.append(line)
    return "\n".join(lines)


def format_seed_for_prompt(seed) -> str:
    """Render a chat handoff seed as generation material (design doc 11 §5.6).

    The chat answer is the substance and its sources are the citations, so both
    go in the `{items}` slot the templates already interpolate — no template
    edits, and every category's custom prompt keeps working unchanged.
    """
    lines = ["- CHAT INVESTIGATION (the owner developed this in research chat; "
             "it is the basis for this piece)"]
    if seed.theme:
        lines.append(f"  THEME: {seed.theme}")
    if seed.summary:
        lines.append(f"  FINDINGS: {seed.summary}")
    for src in seed.sources:
        line = f"- {src.title or src.url}\n  {src.snippet}".rstrip()
        lines.append(f"{line}\n  {src.url}")
    return "\n".join(lines)


def seed_block(seed) -> str:
    """Instruction appended when generating from a chat handoff."""
    if not seed:
        return ""
    return (
        "\n\nSOURCE OF THIS PIECE — the material above came from the owner's own "
        "research chat, not the usual collection feed. Stay on its theme and use "
        "its findings and sources as the basis. Do not introduce unrelated topics."
    )
