"""Publish a teaser + link to Mastodon (optional, off by default).

Verified against the Mastodon REST API:

* ``POST {instance}/api/v1/statuses`` with header ``Authorization: Bearer <token>``
* form field ``status`` (and optional ``visibility``)
* the response carries the ``id`` and the post ``url``
"""

from __future__ import annotations

import logging

from ..util.http import RetryPolicy, post_json
from ..util.text import grapheme_len, truncate_graphemes
from .base import PublishResult, post_url

logger = logging.getLogger(__name__)

DEFAULT_LIMIT = 500
_POLICY = RetryPolicy(attempts=3, backoff_base=1.0, timeout=20.0)


def build_status(article: dict, settings, limit: int = DEFAULT_LIMIT) -> str:
    """Teaser plus link, within Mastodon's character limit."""
    teaser = (article.get("teaser") or "").strip()
    link = article.get("url") or post_url(settings, article.get("slug", ""))
    if not link:
        return truncate_graphemes(teaser, limit)
    if not teaser:
        return link
    budget = limit - grapheme_len(link) - 2
    if budget <= 1:
        return link
    return f"{truncate_graphemes(teaser, budget)}\n\n{link}"


def mastodon_poster(article: dict, settings) -> PublishResult:
    """Post to Mastodon. Never raises."""
    if not settings.mastodon_instance or not settings.mastodon_access_token:
        return PublishResult(target="mastodon", ok=False, error="MASTODON_INSTANCE/MASTODON_ACCESS_TOKEN not set")

    status = build_status(article, settings)
    if not status.strip():
        return PublishResult(target="mastodon", skipped=True, error="empty status")

    url = f"{settings.mastodon_instance.rstrip('/')}/api/v1/statuses"
    headers = {"Authorization": f"Bearer {settings.mastodon_access_token}"}
    try:
        response = post_json(url, data={"status": status, "visibility": "public"}, headers=headers, policy=_POLICY)
        data = response.json()
    except Exception as exc:
        logger.error("event=mastodon_failed error=%s", exc)
        return PublishResult(target="mastodon", ok=False, error=str(exc))

    post_url_value = str(data.get("url") or "")
    external_id = str(data.get("id") or "")
    logger.info("event=mastodon_ok url=%s", post_url_value)
    return PublishResult(target="mastodon", ok=True, url=post_url_value, external_id=external_id)
