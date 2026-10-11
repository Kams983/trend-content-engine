"""Publish to DEV.to via the Forem API.

Verified against the Forem API spec (``POST /api/articles``):

* header ``api-key: <key>`` plus ``Content-Type: application/json``
* body ``{"article": {title, body_markdown, published, tags, canonical_url, description}}``
* tags are capped at 4 and must be lowercase alphanumeric
* the response carries the article ``id`` and ``url``
"""

from __future__ import annotations

import logging
import re

from ..util.http import RetryPolicy, post_json
from .base import PublishResult, build_description, post_url

logger = logging.getLogger(__name__)

API_URL = "https://dev.to/api/articles"
MAX_TAGS = 4
_POLICY = RetryPolicy(attempts=3, backoff_base=1.0, timeout=20.0)
_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def devto_tags(tags: list[str], limit: int = MAX_TAGS) -> list[str]:
    """Lowercase alphanumeric tags (Forem rejects anything else)."""
    cleaned: list[str] = []
    for tag in tags:
        slug = _NON_ALNUM.sub("", str(tag).lower())
        if slug and slug not in cleaned:
            cleaned.append(slug)
    return cleaned[:limit]


def build_payload(article: dict, settings) -> dict:
    return {
        "article": {
            "title": (article.get("title") or "")[:128],
            "body_markdown": article.get("body_markdown") or "",
            "published": True,
            "description": build_description(article.get("teaser", "")),
            "tags": devto_tags(article.get("tags") or []),
            "canonical_url": article.get("url") or post_url(settings, article.get("slug", "")),
        }
    }


def devto_poster(article: dict, settings) -> PublishResult:
    """Create the article on DEV.to. Never raises."""
    if not settings.devto_api_key:
        return PublishResult(target="devto", ok=False, error="DEVTO_API_KEY not set")

    headers = {"api-key": settings.devto_api_key, "Content-Type": "application/json"}
    try:
        response = post_json(API_URL, json=build_payload(article, settings), headers=headers, policy=_POLICY)
        data = response.json()
    except Exception as exc:
        logger.error("event=devto_failed error=%s", exc)
        return PublishResult(target="devto", ok=False, error=str(exc))

    url = str(data.get("url") or "")
    external_id = str(data.get("id") or "")
    if not url:
        return PublishResult(target="devto", ok=False, error="response missing article url")
    logger.info("event=devto_ok url=%s", url)
    return PublishResult(target="devto", ok=True, url=url, external_id=external_id)
