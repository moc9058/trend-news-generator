"""Channel-specific text rendering and length rules.

X counts weighted characters: most CJK/wide chars weigh 2, everything else 1,
and any URL counts as 23 regardless of its real length. Threads counts plain
characters (limit 500).
"""

import re
import unicodedata

X_LIMIT = 280
THREADS_LIMIT = 500
_URL_RE = re.compile(r"https?://\S+")
_TCO_WEIGHT = 23


def _char_weight(ch: str) -> int:
    if unicodedata.east_asian_width(ch) in ("F", "W", "A"):
        return 2
    return 1


def x_weighted_length(text: str) -> int:
    total = 0
    pos = 0
    for match in _URL_RE.finditer(text):
        for ch in text[pos : match.start()]:
            total += _char_weight(ch)
        total += _TCO_WEIGHT
        pos = match.end()
    for ch in text[pos:]:
        total += _char_weight(ch)
    return total


def fits_x(text: str) -> bool:
    return x_weighted_length(text) <= X_LIMIT


def fits_threads(text: str) -> bool:
    return len(text) <= THREADS_LIMIT


def split_for_x_thread(text: str, limit: int = X_LIMIT) -> list[str]:
    """Split text into a reply chain, breaking on sentence/whitespace boundaries.
    Each part gets an " (i/n)" suffix when there are multiple parts."""
    if x_weighted_length(text) <= limit:
        return [text]

    budget = limit - 8  # room for " (10/10)"
    sentences = re.split(r"(?<=[.!?。！？])\s*", text)
    parts: list[str] = []
    current = ""
    for sentence in sentences:
        if not sentence:
            continue
        candidate = (current + " " + sentence).strip() if current else sentence
        if x_weighted_length(candidate) <= budget:
            current = candidate
            continue
        if current:
            parts.append(current)
            current = ""
        # sentence alone exceeds budget → hard-wrap on weight
        chunk = ""
        for ch in sentence:
            if x_weighted_length(chunk + ch) > budget:
                parts.append(chunk)
                chunk = ch
            else:
                chunk += ch
        current = chunk
    if current:
        parts.append(current)

    total = len(parts)
    if total == 1:
        return parts
    return [f"{p} ({i}/{total})" for i, p in enumerate(parts, start=1)]


def strip_urls(text: str) -> str:
    return _URL_RE.sub("", text).replace("  ", " ").strip()


def append_url(text: str, url: str, limit_check) -> str:
    """Append a URL, trimming the text if the combination exceeds the limit."""
    candidate = f"{text}\n{url}"
    while not limit_check(candidate) and len(text) > 10:
        text = text[:-10].rstrip()
        candidate = f"{text}…\n{url}"
    return candidate
