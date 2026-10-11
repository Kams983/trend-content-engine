"""Publisher registry.

``get_publishers(settings)`` returns the enabled targets in a stable order.
The orchestrator is responsible for idempotency (the ``publications`` table) and
for dry-run behaviour (never calling these in ``--dry-run``).
"""

from __future__ import annotations

import json
import logging
from typing import Callable

from .base import Publisher, PublishResult, as_publication_article, build_description, post_url
from .bluesky_poster import bluesky_poster
from .devto_poster import devto_poster
from .hashnode_poster import hashnode_poster
from .mastodon_poster import mastodon_poster
from .site_publisher import site_publisher
from .telegram_poster import telegram_poster

logger = logging.getLogger(__name__)

#: target name → publish function
REGISTRY: dict[str, Callable[[dict, object], PublishResult]] = {
    "site": site_publisher,
    "bluesky": bluesky_poster,
    "telegram": telegram_poster,
    "devto": devto_poster,
    "hashnode": hashnode_poster,
    "mastodon": mastodon_poster,
}


def get_publishers(settings) -> list[tuple[str, Callable[[dict, object], PublishResult]]]:
    """Enabled ``(name, fn)`` pairs, in a stable order."""
    return [(name, REGISTRY[name]) for name in settings.enabled_targets if name in REGISTRY]


def preview_publication(article: dict, settings, target: str) -> str:
    """Human-readable description of what *would* be sent (used by --dry-run)."""
    enriched = as_publication_article(article, article.get("slug", ""), settings)
    if target == "site":
        return f"would write {settings.content_posts_dir}/{enriched['slug']}.md"
    if target in {"bluesky", "telegram", "mastodon"}:
        body = enriched.get("teaser", "")
    else:
        body = build_description(enriched.get("teaser", ""))
    return json.dumps(
        {
            "target": target,
            "url": enriched.get("url", ""),
            "title": enriched.get("title", ""),
            "text": body,
        },
        ensure_ascii=False,
    )


__all__ = [
    "Publisher",
    "PublishResult",
    "REGISTRY",
    "as_publication_article",
    "build_description",
    "get_publishers",
    "post_url",
    "preview_publication",
]
