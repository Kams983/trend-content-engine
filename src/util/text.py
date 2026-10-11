"""Pure text helpers shared across ingest, generation and publishing."""

from __future__ import annotations

import json
import re
import unicodedata
from html.parser import HTMLParser
from typing import Any

# ---------------------------------------------------------------------------
# HTML → text
# ---------------------------------------------------------------------------


class _HTMLStripper(HTMLParser):
    """Minimal stdlib HTML-to-text converter."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self._parts.append(data)

    def get_text(self) -> str:
        return " ".join(self._parts)


def strip_html(raw: str) -> str:
    """Remove HTML tags, collapse whitespace, drop stray entities."""
    if not raw:
        return ""
    if "<" not in raw and "&" not in raw:
        return re.sub(r"\s+", " ", raw).strip()  # fast path
    stripper = _HTMLStripper()
    stripper.feed(raw)
    text = stripper.get_text()
    text = re.sub(r"&[a-zA-Z]+;|&#\d+;", " ", text)
    return re.sub(r"\s+", " ", text).strip()


# ---------------------------------------------------------------------------
# Slugs
# ---------------------------------------------------------------------------

_SLUG_STRIP = re.compile(r"[^a-z0-9]+")


def slugify(title: str, max_len: int = 80) -> str:
    """URL slug: lowercase ASCII, non-alphanumerics → single hyphens."""
    text = unicodedata.normalize("NFKD", title or "")
    text = text.encode("ascii", "ignore").decode("ascii").lower()
    slug = _SLUG_STRIP.sub("-", text).strip("-")
    slug = re.sub(r"-{2,}", "-", slug)
    slug = slug[:max_len].strip("-")
    return slug or "untitled"


def slugify_unique(title: str, taken: set[str], max_len: int = 80) -> str:
    """Slug that never collides with *taken* (appends ``-2``, ``-3``, …)."""
    base = slugify(title, max_len=max_len)
    if base not in taken:
        return base
    counter = 2
    while True:
        suffix = f"-{counter}"
        candidate = f"{base[: max_len - len(suffix)]}{suffix}"
        if candidate not in taken:
            return candidate
        counter += 1


# ---------------------------------------------------------------------------
# Counting
# ---------------------------------------------------------------------------


def count_words(text: str) -> int:
    """Word count using ``\\w+`` tokens (markdown-aware enough for validation)."""
    return len(re.findall(r"\S+", text or ""))


def grapheme_len(text: str) -> int:
    """Number of user-perceived characters (Bluesky's 300 limit is graphemes)."""
    if not text:
        return 0
    try:
        import grapheme  # type: ignore

        return grapheme.length(text)
    except Exception:  # pragma: no cover - grapheme is a declared dependency
        return len(text)


def truncate_graphemes(text: str, limit: int, suffix: str = "…") -> str:
    """Truncate *text* to at most *limit* graphemes, appending *suffix* if cut."""
    if grapheme_len(text) <= limit:
        return text
    if limit <= len(suffix):
        return suffix[:limit]
    target = limit - len(suffix)
    try:
        import grapheme  # type: ignore

        return grapheme.slice(text, end=target) + suffix
    except Exception:  # pragma: no cover
        return text[:target] + suffix


# ---------------------------------------------------------------------------
# JSON extraction from LLM output
# ---------------------------------------------------------------------------

_FENCE = re.compile(r"^\s*```[a-zA-Z0-9_-]*\s*|\s*```\s*$")


def strip_code_fences(text: str) -> str:
    """Remove a single surrounding ```json ... ``` fence, if present."""
    stripped = (text or "").strip()
    if not stripped.startswith("```"):
        return stripped
    lines = stripped.splitlines()
    if len(lines) >= 2 and lines[0].strip().startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip().startswith("```"):
        lines = lines[:-1]
    return "\n".join(lines).strip()


def extract_json_object(text: str) -> dict[str, Any] | None:
    """Best-effort parse of a JSON object from possibly-fenced LLM text.

    Returns ``None`` when no object can be parsed. Never raises.
    """
    if not text:
        return None
    candidate = strip_code_fences(text)
    for attempt in (candidate, _first_balanced_object(candidate)):
        if not attempt:
            continue
        try:
            parsed = json.loads(attempt)
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(parsed, dict):
            return parsed
    return None


def _first_balanced_object(text: str) -> str | None:
    """Return the first balanced ``{...}`` substring, respecting strings."""
    start = text.find("{")
    if start < 0:
        return None
    depth = 0
    in_string = False
    escaped = False
    for idx in range(start, len(text)):
        ch = text[idx]
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : idx + 1]
    return None
