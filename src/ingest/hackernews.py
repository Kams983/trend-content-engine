"""Pull today's top stories from Hacker News via the official Firebase API."""

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

logger = logging.getLogger(__name__)

HN_TOP = "https://hacker-news.firebaseio.com/v0/topstories.json"
HN_ITEM = "https://hacker-news.firebaseio.com/v0/item/{}.json"
LIMIT = 30


def _fetch_one(story_id: int) -> dict | None:
    try:
        item = requests.get(HN_ITEM.format(story_id), timeout=5).json()
        if item and item.get("type") == "story":
            return item
    except Exception as exc:
        logger.debug("HN item %s failed: %s", story_id, exc)
    return None


def fetch() -> list[dict]:
    """Return raw dicts for the top HN stories."""
    try:
        resp = requests.get(HN_TOP, timeout=10)
        resp.raise_for_status()
        ids = resp.json()[:LIMIT]
    except Exception as exc:
        logger.warning("HN top-stories fetch failed: %s", exc)
        return []

    items: list[dict] = []
    with ThreadPoolExecutor(max_workers=10) as pool:
        futures = {pool.submit(_fetch_one, sid): sid for sid in ids}
        for fut in as_completed(futures):
            if (result := fut.result()) is not None:
                items.append(result)
    return items


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    for item in fetch()[:3]:
        print(f"  {item.get('title', '?')[:60]}  ({item.get('score', 0)} pts)")
