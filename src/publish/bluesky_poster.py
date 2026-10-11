"""Post an article teaser + link card to Bluesky via the AT Protocol.

Verified against atproto **0.0.71**:

* ``atproto.Client.login(handle, password)``
* ``Client.send_post(text, embed=..., facets=..., langs=...)`` where ``embed``
  is ``models.AppBskyEmbedExternal.Main``
* facets are ``models.AppBskyRichtextFacet.Main`` with a ``ByteSlice`` index
  (UTF-8 **byte** offsets) and a ``Link`` feature

Bluesky's limit is 300 *graphemes*, not characters, so truncation uses
:func:`src.util.text.grapheme_len`.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from ..util.text import grapheme_len, truncate_graphemes
from .base import PublishResult, build_description, post_url

logger = logging.getLogger(__name__)

BLUESKY_LIMIT = 300
_URL_RE = re.compile(r"https?://[^\s]+")


def build_post_text(teaser: str, url: str = "", limit: int = BLUESKY_LIMIT) -> str:
    """Teaser plus link, guaranteed to fit Bluesky's grapheme limit."""
    text = (teaser or "").strip()
    url = (url or "").strip()
    if not url:
        return truncate_graphemes(text, limit)
    if not text:
        return url
    if grapheme_len(text) + 2 + grapheme_len(url) <= limit:
        return f"{text}\n\n{url}"
    room = limit - grapheme_len(url) - 2
    if room <= 1:
        return url
    return f"{truncate_graphemes(text, room)}\n\n{url}"


def build_facets(text: str) -> list[Any]:
    """URL facets with correct UTF-8 byte offsets (imports atproto lazily)."""
    from atproto import models

    facets: list[Any] = []
    for match in _URL_RE.finditer(text):
        url = match.group(0)
        byte_start = len(text[: match.start()].encode("utf-8"))
        byte_end = byte_start + len(url.encode("utf-8"))
        facets.append(
            models.AppBskyRichtextFacet.Main(
                index=models.AppBskyRichtextFacet.ByteSlice(byteStart=byte_start, byteEnd=byte_end),
                features=[models.AppBskyRichtextFacet.Link(uri=url)],
            )
        )
    return facets


def build_external_embed(url: str, title: str, description: str) -> Any:
    """Link-card embed; the site's OG image is attached by Bluesky from the URL."""
    from atproto import models

    return models.AppBskyEmbedExternal.Main(
        external=models.AppBskyEmbedExternal.External(
            uri=url,
            title=(title or "")[:300],
            description=(description or "")[:1000],
        )
    )


def bluesky_poster(article: dict, settings) -> PublishResult:
    """Post the teaser + link to Bluesky. Never raises."""
    handle = settings.bluesky_handle
    password = settings.bluesky_app_password
    if not handle or not password:
        return PublishResult(target="bluesky", ok=False, error="BLUESKY_HANDLE/BLUESKY_APP_PASSWORD not set")

    teaser = (article.get("teaser") or "").strip()
    if not teaser:
        return PublishResult(target="bluesky", skipped=True, error="empty teaser")

    link = article.get("url") or post_url(settings, article.get("slug", ""))
    text = build_post_text(teaser, link)
    facets = build_facets(text)
    embed = build_external_embed(link, article.get("title", ""), build_description(teaser, 200))

    try:
        from atproto import Client

        client = Client()
        client.login(handle, password)
        response = client.send_post(text, embed=embed, facets=facets, langs=["en"])
    except Exception as exc:
        logger.error("event=bluesky_failed error=%s", exc)
        return PublishResult(target="bluesky", ok=False, error=str(exc))

    rkey = str(getattr(response, "uri", "")).rsplit("/", 1)[-1]
    url = f"https://bsky.app/profile/{handle}/post/{rkey}" if rkey else ""
    logger.info("event=bluesky_ok url=%s", url)
    return PublishResult(target="bluesky", ok=True, url=url, external_id=rkey)
