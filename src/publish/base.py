"""Shared publisher types and helpers.

Every publisher returns a :class:`PublishResult` and never raises — the
orchestrator records the result in the ``publications`` table.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Protocol

logger = logging.getLogger(__name__)


@dataclass
class PublishResult:
    """Outcome of publishing one article to one target."""

    target: str
    ok: bool = False
    skipped: bool = False
    url: str = ""
    external_id: str = ""
    error: str = ""

    @property
    def status(self) -> str:
        if self.skipped:
            return "skipped"
        return "ok" if self.ok else "failed"


class Publisher(Protocol):
    """A publishing target."""

    name: str

    def publish(self, article: dict, settings) -> PublishResult: ...


def post_url(settings, slug: str) -> str:
    """Absolute URL of a post on the site (no trailing slash)."""
    base = (getattr(settings, "site_url", "") or "").rstrip("/")
    return f"{base}/posts/{slug}" if base else f"/posts/{slug}"


def build_description(teaser: str, limit: int = 155) -> str:
    """A single-line meta description from the teaser."""
    text = " ".join((teaser or "").split())
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def as_publication_article(article: dict, slug: str, settings) -> dict:
    """Normalise an article dict for publishers (adds slug/url/description)."""
    enriched = dict(article)
    enriched.setdefault("slug", slug)
    enriched.setdefault("url", post_url(settings, slug))
    enriched.setdefault("description", build_description(article.get("teaser", "")))
    return enriched
