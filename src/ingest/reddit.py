"""Fetch hot posts from r/programming via Reddit's Atom feed (no key)."""

import logging
import xml.etree.ElementTree as ET

import requests

logger = logging.getLogger(__name__)

RSS_URL = "https://www.reddit.com/r/programming/hot/.rss"
ATOM_NS = "{http://www.w3.org/2005/Atom}"
UA = "linux:trending-content-engine:v1.0 (by /u/content-engine-bot)"
LIMIT = 30


def fetch() -> list[dict]:
    """Return raw dicts for the hot posts on r/programming."""
    params = {"limit": LIMIT}
    headers = {"User-Agent": UA}
    try:
        resp = requests.get(RSS_URL, params=params, headers=headers, timeout=10)
        resp.raise_for_status()
    except Exception as exc:
        logger.warning("Reddit fetch failed: %s", exc)
        return []

    items: list[dict] = []
    try:
        root = ET.fromstring(resp.content)
        for entry in root.findall(f"{ATOM_NS}entry"):
            author = entry.find(f"{ATOM_NS}author/{ATOM_NS}name")
            link_el = entry.find(f"{ATOM_NS}link")
            link_href = link_el.get("href", "") if link_el is not None else ""
            items.append({
                "title": (entry.findtext(f"{ATOM_NS}title") or "").strip(),
                "url": link_href,
                "id": (entry.findtext(f"{ATOM_NS}id") or "").strip(),
                "updated": (entry.findtext(f"{ATOM_NS}updated") or "").strip(),
                "author": author.text if author is not None else "",
                "content": (entry.findtext(f"{ATOM_NS}content") or "")[:2000],
            })
    except ET.ParseError as exc:
        logger.warning("Reddit Atom parse error: %s", exc)
    return items


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    for item in fetch()[:3]:
        print(f"  {item['title'][:60]}")
        print(f"    {item['url']}")
