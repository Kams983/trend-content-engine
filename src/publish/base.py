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


def publication_footer(brand: str) -> str:
    """The one line outbound posts use when they point back at the publication.

    Only the PUBLIC brand name appears here — never an internal engine name. An
    empty brand degrades to an empty string rather than a dangling sentence.
    """
    name = (brand or "").strip()
    return f"Read more on {name}" if name else ""


def attribution_line(brand: str, url: str = "") -> str:
    """The publication attribution in the one shape every target shares.

    ``Read more on <brand>`` on its own, or ``Read more on <brand>: <url>`` when
    a link belongs in the text (short-form posts and cross-post bodies).
    """
    footer = publication_footer(brand)
    if not footer:
        return url or ""
    return f"{footer}: {url}" if url else footer


def compose_post_text(teaser: str, url: str = "", limit: int = 300, footer: str = "") -> str:
    """The short-post template: teaser, publication attribution, canonical link.

    Used by every short-form target so a rebrand is one value, not one template
    per platform. The attribution is dropped before the link when the budget is
    tight — the canonical link always survives.
    """
    from ..util.text import grapheme_len, truncate_graphemes

    text = (teaser or "").strip()
    url = (url or "").strip()
    footer = (footer or "").strip()
    link = f"{footer}: {url}" if (footer and url) else url
    if link and grapheme_len(link) > limit:
        link = url
    if not link:
        return truncate_graphemes(text, limit)
    if not text:
        return link
    if grapheme_len(text) + 2 + grapheme_len(link) <= limit:
        return f"{text}\n\n{link}"
    room = limit - grapheme_len(link) - 2
    if room <= 1:
        return link
    return f"{truncate_graphemes(text, room)}\n\n{link}"


def cross_post_body(body: str, url: str, brand: str) -> str:
    """An article body for a cross-post, with the attribution block appended.

    The canonical URL is also sent as the platform's canonical/original field;
    this is the human-readable half, so a reader who lands on the syndicated copy
    can tell where the piece is published.
    """
    line = attribution_line(brand, url)
    if not line:
        return body
    return f"{body.rstrip()}\n\n---\n\n{line}\n"


def build_description(teaser: str, limit: int = 155) -> str:
    """A single-line meta description from the teaser."""
    text = " ".join((teaser or "").split())
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def as_publication_article(article: dict, slug: str, settings) -> dict:
    """Normalise an article dict for publishers (adds slug/url/description/brand).

    The brand fields are added here so no publisher has to reach for a name of
    its own: outbound templates read ``brand_name``/``attribution`` instead.
    """
    enriched = dict(article)
    enriched.setdefault("slug", slug)
    enriched["url"] = enriched.get("url") or post_url(settings, slug)
    enriched.setdefault("description", build_description(article.get("teaser", "")))
    brand = getattr(settings, "brand_name", "") or ""
    enriched.setdefault("brand_name", brand)
    enriched.setdefault("brand_tagline", getattr(settings, "brand_tagline", "") or "")
    enriched.setdefault("attribution", attribution_line(brand, enriched["url"]))
    return enriched
