"""Normalize raw items from every source into a common schema.

Common schema:
    {
        "source":       str,
        "title":        str,
        "content":      str,
        "url":          str,
        "engagement":   int,
        "timestamp":    datetime,   # always UTC-aware
        "tags":         list[str],
    }
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Callable

from ..util.text import strip_html

logger = logging.getLogger(__name__)


def _parse_ts(value: Any) -> datetime:
    """Parse an ISO-8601 timestamp into an aware UTC datetime."""
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not value:
        return datetime.now(timezone.utc)
    text = str(value).strip()
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return datetime.now(timezone.utc)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _norm_hackernews(item: dict) -> dict:
    return {
        "source": "hackernews",
        "title": item.get("title", ""),
        "content": item.get("text") or "",
        "url": item.get("url") or f"https://news.ycombinator.com/item?id={item.get('id', '')}",
        "engagement": int(item.get("score") or 0),
        "timestamp": _parse_ts(datetime.fromtimestamp(item.get("time", 0), tz=timezone.utc) if item.get("time") else None),
        "tags": [],
    }


def _norm_arxiv(item: dict) -> dict:
    return {
        "source": "arxiv",
        "title": item.get("title", ""),
        "content": item.get("summary", ""),
        "url": item.get("url", ""),
        "engagement": len(item.get("authors") or []),
        "timestamp": _parse_ts(item.get("published")),
        "tags": list(item.get("categories") or []),
    }


def _norm_github(item: dict) -> dict:
    tags = list(item.get("topics") or [])
    for extra in (item.get("language", ""), item.get("license", "")):
        if extra and extra not in tags:
            tags.append(extra)
    return {
        "source": "github_trending",
        "title": item.get("full_name", ""),
        "content": item.get("description", ""),
        "url": item.get("html_url", ""),
        "engagement": int(item.get("stargazers_count") or 0),
        "timestamp": _parse_ts(item.get("created_at")),
        "tags": tags,
    }


def _norm_reddit(item: dict) -> dict:
    return {
        "source": "reddit",
        "title": item.get("title", ""),
        "content": item.get("content", ""),
        "url": item.get("url", ""),
        "engagement": 0,  # the Atom feed carries no score
        "timestamp": _parse_ts(item.get("updated")),
        "tags": [],
    }


_NORMALIZERS: dict[str, Callable[[dict], dict]] = {
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
        logger.warning(f"event=unknown_source source={source}")
        return raw_items

    out: list[dict] = []
    for item in raw_items:
        try:
            normalised = fn(item)
            normalised["content"] = strip_html(normalised.get("content", ""))
            if not normalised.get("title"):
                continue
            out.append(normalised)
        except Exception as exc:
            logger.warning(f"event=normalize_failed source={source} error={exc}")
    return out
