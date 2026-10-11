"""Pull recent papers from arXiv via the Atom feed API (no key needed)."""

import logging
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

import requests

logger = logging.getLogger(__name__)

API_URL = "http://export.arxiv.org/api/query"
ATOM_NS = "{http://www.w3.org/2005/Atom}"
CATEGORIES = ["cs.AI", "cs.LG", "cs.CL", "cs.SE", "cs.CV", "cs.RO"]
LIMIT = 30


def fetch() -> list[dict]:
    """Return raw dicts for recent arXiv papers."""
    query = " OR ".join(f"cat:{c}" for c in CATEGORIES)
    params = {
        "search_query": query,
        "sortBy": "submittedDate",
        "sortOrder": "descending",
        "max_results": LIMIT,
    }
    try:
        resp = requests.get(API_URL, params=params, timeout=15)
        resp.raise_for_status()
    except Exception as exc:
        logger.warning("arXiv fetch failed: %s", exc)
        return []

    items: list[dict] = []
    try:
        root = ET.fromstring(resp.content)
        for entry in root.findall(f"{ATOM_NS}entry"):
            item = {
                "title": (entry.findtext(f"{ATOM_NS}title") or "").strip().replace("\n", " "),
                "summary": (entry.findtext(f"{ATOM_NS}summary") or "").strip().replace("\n", " "),
                "url": entry.findtext(f"{ATOM_NS}id") or "",
                "published": entry.findtext(f"{ATOM_NS}published") or "",
                "authors": [
                    (a.findtext(f"{ATOM_NS}name") or "")
                    for a in entry.findall(f"{ATOM_NS}author")
                ],
                "categories": [
                    c.get("term", "") for c in entry.findall(f"{ATOM_NS}category")
                ],
            }
            items.append(item)
    except ET.ParseError as exc:
        logger.warning("arXiv XML parse error: %s", exc)
    return items


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    for item in fetch()[:3]:
        print(f"  {item['title'][:60]}\n    {item['url']}\n    {item['categories']}")
