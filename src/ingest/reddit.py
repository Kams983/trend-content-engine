"""Fetch hot posts from r/programming via Reddit's Atom feed (no key)."""

from __future__ import annotations

import logging
import xml.etree.ElementTree as ET

from ..config import Settings
from ..util.http import RetryPolicy, request
from ..util.logging_setup import kv

logger = logging.getLogger(__name__)

RSS_URL = "https://www.reddit.com/r/programming/hot/.rss"
ATOM_NS = "{http://www.w3.org/2005/Atom}"
_POLICY = RetryPolicy(attempts=3, timeout=15.0)


def fetch(settings: Settings | None = None) -> list[dict]:
    """Return raw dicts for the hot posts on r/programming."""
    cfg = settings or Settings()
    headers = {
        # Reddit's guidance: a descriptive UA with a contact.
        "User-Agent": f"python:trend-content-engine:v1.0 (by /u/trend-engine-bot) [{cfg.user_agent}]",
        "Accept": "application/atom+xml",
    }
    params = {"limit": cfg.reddit_limit}

    try:
        response = request("GET", RSS_URL, params=params, headers=headers, policy=_POLICY)
    except Exception as exc:
        logger.warning(kv("source_fetch_failed", source="reddit", error=str(exc)))
        return []

    items: list[dict] = []
    try:
        root = ET.fromstring(response.content)
        for entry in root.findall(f"{ATOM_NS}entry"):
            author = entry.find(f"{ATOM_NS}author/{ATOM_NS}name")
            link_el = entry.find(f"{ATOM_NS}link")
            items.append(
                {
                    "title": (entry.findtext(f"{ATOM_NS}title") or "").strip(),
                    "url": link_el.get("href", "") if link_el is not None else "",
                    "id": (entry.findtext(f"{ATOM_NS}id") or "").strip(),
                    "updated": (entry.findtext(f"{ATOM_NS}updated") or "").strip(),
                    "author": author.text if author is not None else "",
                    "content": (entry.findtext(f"{ATOM_NS}content") or "")[:2000],
                }
            )
    except ET.ParseError as exc:
        logger.warning(kv("source_parse_failed", source="reddit", error=str(exc)))
    if not items:
        logger.warning(kv("source_empty", source="reddit"))
    return items
