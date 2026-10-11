"""Fetch trending repos from the GitHub Search API.

Uses ``GITHUB_TOKEN`` when present to raise the rate limit (public search needs
no scopes). All HTTP goes through the shared helper.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from ..config import Settings
from ..util.http import RetryPolicy, get_json
from ..util.logging_setup import kv

logger = logging.getLogger(__name__)

API_URL = "https://api.github.com/search/repositories"
_POLICY = RetryPolicy(attempts=3, timeout=15.0)


def fetch(settings: Settings | None = None) -> list[dict]:
    """Return raw dicts for trending repos (created in the last 7 days)."""
    cfg = settings or Settings()
    since = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%d")
    params = {
        "q": f"created:>{since}",
        "sort": "stars",
        "order": "desc",
        "per_page": cfg.github_limit,
    }
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": cfg.user_agent,
    }
    if cfg.github_token:
        headers["Authorization"] = f"Bearer {cfg.github_token}"

    try:
        data = get_json(API_URL, params=params, headers=headers, policy=_POLICY)
    except Exception as exc:
        logger.warning(kv("source_fetch_failed", source="github_trending", error=str(exc)))
        return []

    items: list[dict] = []
    for repo in data.get("items", []) if isinstance(data, dict) else []:
        try:
            items.append(
                {
                    "full_name": repo["full_name"],
                    "description": repo.get("description") or "",
                    "html_url": repo["html_url"],
                    "stargazers_count": repo["stargazers_count"],
                    "language": repo.get("language") or "",
                    "created_at": repo["created_at"],
                    "topics": repo.get("topics") or [],
                    "license": (repo.get("license") or {}).get("spdx_id", ""),
                }
            )
        except (KeyError, TypeError) as exc:
            logger.debug(kv("source_item_skipped", source="github_trending", error=str(exc)))
    if not items:
        logger.warning(kv("source_empty", source="github_trending"))
    return items
