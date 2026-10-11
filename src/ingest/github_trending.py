"""Fetch today's trending repos from GitHub using the Search API (no key)."""

import logging
from datetime import datetime, timedelta, timezone

import requests

logger = logging.getLogger(__name__)

API_URL = "https://api.github.com/search/repositories"
LIMIT = 30


def fetch() -> list[dict]:
    """Return raw dicts for trending GitHub repos (created in last 7 days, by stars)."""
    since = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%d")
    params = {
        "q": f"created:>{since}",
        "sort": "stars",
        "order": "desc",
        "per_page": LIMIT,
    }
    headers = {"Accept": "application/vnd.github+json"}
    try:
        resp = requests.get(API_URL, params=params, headers=headers, timeout=10)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        logger.warning("GitHub trending fetch failed: %s", exc)
        return []

    items: list[dict] = []
    for repo in data.get("items", []):
        try:
            items.append({
                "full_name": repo["full_name"],
                "description": repo.get("description") or "",
                "html_url": repo["html_url"],
                "stargazers_count": repo["stargazers_count"],
                "language": repo.get("language") or "",
                "created_at": repo["created_at"],
                "topics": repo.get("topics") or [],
                "license": (repo.get("license") or {}).get("spdx_id", ""),
            })
        except (KeyError, TypeError) as exc:
            logger.debug("Skipping malformed GitHub repo entry: %s", exc)
    return items


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    for item in fetch()[:3]:
        print(f"  {item['full_name']}  ({item['stargazers_count']} *)")
        print(f"    {item['html_url']}")
