"""Publisher registry.

``get_publishers(settings)`` returns the enabled targets in a stable order.
The orchestrator is responsible for idempotency (the ``publications`` table) and
for dry-run behaviour (never calling these in ``--dry-run``).

Note: the publish functions are imported under underscore-prefixed aliases so
this package does **not** shadow the ``publish.<module>`` submodule names.
Callers can therefore still do ``from .publish import telegram_poster`` and get
the module (needed for monkeypatching in tests and for the approval handler).
"""

from __future__ import annotations

import json
import logging
from typing import Callable

from .base import (
    Publisher,
    PublishResult,
    as_publication_article,
    attribution_line,
    build_description,
    compose_post_text,
    cross_post_body,
    post_url,
    publication_footer,
)
from .bluesky_poster import bluesky_poster as _bluesky_poster
from .devto_poster import devto_poster as _devto_poster
from .hashnode_poster import hashnode_poster as _hashnode_poster
from .mastodon_poster import mastodon_poster as _mastodon_poster
from .site_publisher import site_publisher as _site_publisher
from .telegram_poster import telegram_poster as _telegram_poster

logger = logging.getLogger(__name__)

#: target name → publish function
REGISTRY: dict[str, Callable[[dict, object], PublishResult]] = {
    "site": _site_publisher,
    "bluesky": _bluesky_poster,
    "telegram": _telegram_poster,
    "devto": _devto_poster,
    "hashnode": _hashnode_poster,
    "mastodon": _mastodon_poster,
}


def get_publishers(settings) -> list[tuple[str, Callable[[dict, object], PublishResult]]]:
    """Enabled ``(name, fn)`` pairs, in a stable order."""
    return [(name, REGISTRY[name]) for name in settings.enabled_targets if name in REGISTRY]


def preview_publication(article: dict, settings, target: str) -> str:
    """Human-readable description of what *would* be sent (used by --dry-run).

    The preview is rendered with the same branded templates the target itself
    uses, so a dry run shows the reader exactly what would go out — including the
    publication name and its attribution line.
    """
    enriched = as_publication_article(article, article.get("slug", ""), settings)
    brand = enriched.get("brand_name", "")
    if target == "site":
        return f"would write {settings.content_posts_dir}/{enriched['slug']}.md"
    if target == "bluesky":
        body = compose_post_text(
            enriched.get("teaser", ""), enriched.get("url", ""), limit=300, footer=publication_footer(brand)
        )
    elif target == "mastodon":
        body = compose_post_text(
            enriched.get("teaser", ""), enriched.get("url", ""), limit=500, footer=publication_footer(brand)
        )
    elif target == "telegram":
        from .telegram_poster import build_channel_message

        body = build_channel_message(enriched, settings)
    else:
        body = build_description(enriched.get("teaser", ""))
        if brand:
            body = f"{body} — {brand}"
    return json.dumps(
        {
            "target": target,
            "url": enriched.get("url", ""),
            "title": enriched.get("title", ""),
            "brand": brand,
            "attribution": enriched.get("attribution", ""),
            "text": body,
        },
        ensure_ascii=False,
    )


__all__ = [
    "Publisher",
    "PublishResult",
    "REGISTRY",
    "as_publication_article",
    "attribution_line",
    "build_description",
    "compose_post_text",
    "cross_post_body",
    "get_publishers",
    "post_url",
    "preview_publication",
    "publication_footer",
]
