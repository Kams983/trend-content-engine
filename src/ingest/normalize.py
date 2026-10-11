"""Normalize raw items from every source into a common schema.

Common schema:
    {
        "source":       str,
        "title":        str,
        "content":      str,
        "url":          str,
        "engagement":   int,
        "timestamp":    datetime,
        "tags":         list[str],
    }
"""

import re
from datetime import datetime, timezone
from html.parser import HTMLParser
from typing import Any

_vlog: Any = None  # lazy import to avoid circulars


def _log():
    global _vlog
    if _vlog is None:
        import logging
        _vlog = logging.getLogger(__name__)
    return _vlog


class _HTMLStripper(HTMLParser):
    """Minimal stdlib HTML-to-text converter."""
    def __init__(self) -> None:
        super().__init__()
        self._parts: list[str] = []
    def handle_data(self, data: str) -> None:
        self._parts.append(data)
    def get_text(self) -> str:
        return " ".join(self._parts)


def _strip_html(raw: str) -> str:
    """Remove HTML tags, collapse whitespace, strip entities."""
    if "<" not in raw and "&" not in raw:
        return raw  # fast path: no tags or entities
    s = _HTMLStripper()
    s.feed(raw)
    text = s.get_text()
    text = re.sub(r"&[a-zA-Z]+;|&#\d+;", " ", text)   # strip stray entities
    return re.sub(r"\s+", " ", text).strip()


# ---------------------------------------------------------------------------
# Per-source normalizers
# ---------------------------------------------------------------------------

def _norm_hackernews(item: dict) -> dict:
    ts = datetime.fromtimestamp(item.get("time", 0), tz=timezone.utc)
    return {
        "source": "hackernews",
        "title": item.get("title", ""),
        "content": item.get("text") or "",
        "url": item.get("url") or f"https://news.ycombinator.com/item?id={item.get('id', '')}",
        "engagement": item.get("score", 0),
        "timestamp": ts,
        "tags": [],
    }


def _norm_arxiv(item: dict) -> dict:
    ts = datetime.fromisoformat(item["published"].replace("Z", "+00:00")) if item.get("published") else datetime.now(timezone.utc)
    return {
        "source": "arxiv",
        "title": item.get("title", ""),
        "content": item.get("summary", ""),
        "url": item.get("url", ""),
        "engagement": len(item.get("authors", [])),
        "timestamp": ts,
        "tags": item.get("categories", []),
    }


def _norm_github(item: dict) -> dict:
    ts = datetime.fromisoformat(item["created_at"].replace("Z", "+00:00")) if item.get("created_at") else datetime.now(timezone.utc)
    tags = list(item.get("topics", []))
    lang = item.get("language", "")
    if lang and lang not in tags:
        tags.append(lang)
    lic = item.get("license", "")
    if lic and lic not in tags:
        tags.append(lic)
    return {
        "source": "github_trending",
        "title": item.get("full_name", ""),
        "content": item.get("description", ""),
        "url": item.get("html_url", ""),
        "engagement": item.get("stargazers_count", 0),
        "timestamp": ts,
        "tags": tags,
    }


def _norm_reddit(item: dict) -> dict:
    ts = datetime.fromisoformat(item["updated"].replace("Z", "+00:00")) if item.get("updated") else datetime.now(timezone.utc)
    return {
        "source": "reddit",
        "title": item.get("title", ""),
        "content": item.get("content", ""),
        "url": item.get("url", ""),
        "engagement": 0,  # RSS doesn't carry score
        "timestamp": ts,
        "tags": [],
    }


_NORMALIZERS = {
    "hackernews": _norm_hackernews,
    "arxiv": _norm_arxiv,
    "github_trending": _norm_github,
    "reddit": _norm_reddit,
}


def normalize(raw_items: list[dict], source: str) -> list[dict]:
    """Map *raw_items* from *source* into the common schema.

    Unknown sources are passed through unchanged (logged as a warning).
    """
    fn = _NORMALIZERS.get(source)
    if fn is None:
        _log().warning("Unknown source %r — returning raw items", source)
        return raw_items

    out: list[dict] = []
    for item in raw_items:
        try:
            normalised = fn(item)
            normalised["content"] = _strip_html(normalised.get("content", ""))
            out.append(normalised)
        except Exception as exc:
            _log().warning("Normalise failed for %s item: %s", source, exc)
    return out
