"""Pull recent papers from the arXiv Atom API (no key needed).

Respects arXiv's polite-usage guidance: a descriptive User-Agent identifying
the tool, and a delay between requests (``ARXIV_POLITENESS_DELAY``, default 3s).
"""

from __future__ import annotations

import logging
import xml.etree.ElementTree as ET

from ..config import Settings
from ..util.http import RetryPolicy, request
from ..util.logging_setup import kv

logger = logging.getLogger(__name__)

API_URL = "https://export.arxiv.org/api/query"
ATOM_NS = "{http://www.w3.org/2005/Atom}"
CATEGORIES = ["cs.AI", "cs.LG", "cs.CL", "cs.SE", "cs.CV", "cs.RO"]

_POLICY = RetryPolicy(attempts=3, backoff_base=1.0, timeout=20.0)


def fetch(settings: Settings | None = None) -> list[dict]:
    """Return raw dicts for recent arXiv papers (empty list on failure)."""
    cfg = settings or Settings()
    query = " OR ".join(f"cat:{c}" for c in CATEGORIES)
    params = {
        "search_query": query,
        "sortBy": "submittedDate",
        "sortOrder": "descending",
        "max_results": cfg.arxiv_limit,
    }
    headers = {"User-Agent": f"{cfg.user_agent} (mailto:ops@example.com)", "Accept": "application/atom+xml"}

    # arXiv asks for no more than ~1 request every 3 seconds.
    if cfg.arxiv_politeness_delay > 0:
        import time

        time.sleep(cfg.arxiv_politeness_delay)

    try:
        response = request("GET", API_URL, params=params, headers=headers, policy=_POLICY)
    except Exception as exc:
        logger.warning(kv("source_fetch_failed", source="arxiv", error=str(exc)))
        return []

    items: list[dict] = []
    try:
        root = ET.fromstring(response.content)
        for entry in root.findall(f"{ATOM_NS}entry"):
            items.append(
                {
                    "title": (entry.findtext(f"{ATOM_NS}title") or "").strip().replace("\n", " "),
                    "summary": (entry.findtext(f"{ATOM_NS}summary") or "").strip().replace("\n", " "),
                    "url": entry.findtext(f"{ATOM_NS}id") or "",
                    "published": entry.findtext(f"{ATOM_NS}published") or "",
                    "authors": [(a.findtext(f"{ATOM_NS}name") or "") for a in entry.findall(f"{ATOM_NS}author")],
                    "categories": [c.get("term", "") for c in entry.findall(f"{ATOM_NS}category")],
                }
            )
    except ET.ParseError as exc:
        logger.warning(kv("source_parse_failed", source="arxiv", error=str(exc)))
    if not items:
        logger.warning(kv("source_empty", source="arxiv"))
    return items
