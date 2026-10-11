"""Pull today's top stories from Hacker News via the official Firebase API.

All HTTP goes through :mod:`src.util.http` so retries/backoff and the shared
User-Agent are applied uniformly.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor

from ..config import Settings
from ..util.http import RetryPolicy, get_json
from ..util.logging_setup import kv

logger = logging.getLogger(__name__)

HN_TOP = "https://hacker-news.firebaseio.com/v0/topstories.json"
HN_ITEM = "https://hacker-news.firebaseio.com/v0/item/{}.json"

_ITEM_POLICY = RetryPolicy(attempts=2, timeout=8.0)


def _fetch_one(story_id: int) -> dict | None:
    try:
        item = get_json(HN_ITEM.format(story_id), policy=_ITEM_POLICY)
    except Exception as exc:  # non-fatal per item
        logger.debug(kv("hn_item_failed", story_id=story_id, error=str(exc)))
        return None
    if item and item.get("type") == "story":
        return item
    return None


def fetch(settings: Settings | None = None) -> list[dict]:
    """Return raw dicts for the top HN stories (empty list on failure)."""
    cfg = settings or Settings()
    try:
        ids = get_json(HN_TOP, policy=RetryPolicy(attempts=3, timeout=10.0))[: cfg.hn_limit]
    except Exception as exc:
        logger.warning(kv("source_fetch_failed", source="hackernews", error=str(exc)))
        return []

    items: list[dict] = []
    with ThreadPoolExecutor(max_workers=10) as pool:
        for result in pool.map(_fetch_one, ids):
            if result is not None:
                items.append(result)
    if not items:
        logger.warning(kv("source_empty", source="hackernews", story_ids=len(ids)))
    return items
