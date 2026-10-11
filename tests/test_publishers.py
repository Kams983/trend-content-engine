"""Publisher-specific behaviour: facets, graphemes, escaping and payloads.

Outbound payloads always carry an absolute canonical link, so the tests below
configure ``SITE_URL`` and assert on the full URL rather than a path suffix.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from src.config import Settings
from src.publish.base import MissingSiteUrl, post_url
from src.publish.bluesky_poster import BLUESKY_LIMIT, build_facets, build_post_text, bluesky_poster
from src.publish.devto_poster import build_payload as devto_payload, devto_tags
from src.publish.hashnode_poster import build_variables as hashnode_variables, hashnode_tags
from src.publish.mastodon_poster import build_status
from src.publish.site_publisher import build_frontmatter, site_publisher
from src.publish.telegram_poster import build_approval_keyboard, build_channel_message, escape_html
from src.util.text import grapheme_len

#: A production-shaped origin, so every assertion can check the whole URL.
SITE = "https://upwire.example.test"
CANONICAL = f"{SITE}/posts/2026-01-01-hello"

ARTICLE = {
    "slug": "2026-01-01-hello",
    "title": "Hello <world> & friends",
    "teaser": "A short teaser about things.",
    "body_markdown": "Body.",
    "tags": ["AI", "web dev", "Python!", "extra", "fifth"],
    "topic_id": 3,
    "sources": [{"title": "S", "url": "https://a.test", "source": "hackernews"}],
}


# --- Bluesky ---------------------------------------------------------------


def test_post_text_fits_limit_and_includes_link() -> None:
    text = build_post_text("teaser", "https://example.test/posts/x")
    assert text.endswith("https://example.test/posts/x")
    assert grapheme_len(text) <= BLUESKY_LIMIT


def test_post_text_truncates_long_teaser() -> None:
    teaser = "word " * 200
    text = build_post_text(teaser, "https://example.test/posts/x")
    assert grapheme_len(text) <= BLUESKY_LIMIT
    assert "https://example.test/posts/x" in text


def test_post_text_counts_graphemes_not_codepoints() -> None:
    teaser = "👨‍👩‍👧" * 200  # 200 graphemes but 800 codepoints
    text = build_post_text(teaser, "https://example.test/posts/x")
    assert grapheme_len(text) <= BLUESKY_LIMIT


def test_post_text_without_link() -> None:
    assert build_post_text("just a teaser", "") == "just a teaser"


def test_facets_use_utf8_byte_offsets() -> None:
    text = "café https://example.test/x"
    facets = build_facets(text)
    assert len(facets) == 1
    facet = facets[0]
    expected_start = len("café ".encode("utf-8"))  # é is two bytes
    # atproto exposes snake_case attributes (the constructor accepts the aliases).
    assert facet.index.byte_start == expected_start
    assert facet.index.byte_end == expected_start + len("https://example.test/x".encode("utf-8"))
    assert facet.features[0].uri == "https://example.test/x"


def test_facets_empty_when_no_url() -> None:
    assert build_facets("no links here") == []


# --- Telegram --------------------------------------------------------------


def test_escape_html() -> None:
    assert escape_html("a & b < c > d") == "a &amp; b &lt; c &gt; d"


def test_escape_html_escapes_ampersand_first() -> None:
    assert escape_html("<&>") == "&lt;&amp;&gt;"


def test_channel_message_escapes_title(settings) -> None:
    message = build_channel_message(ARTICLE, settings)
    assert "&lt;world&gt;" in message
    assert "<world>" not in message
    assert "https://example.test/posts/2026-01-01-hello" in message


def test_approval_keyboard_encodes_article_id() -> None:
    keyboard = build_approval_keyboard(42)
    callbacks = [button["callback_data"] for row in keyboard["inline_keyboard"] for button in row]
    assert callbacks == ["approve:42", "reject:42"]


# --- DEV.to ----------------------------------------------------------------


def test_devto_tags_are_lowercase_alnum_and_capped() -> None:
    assert devto_tags(["AI", "web dev", "Python!", "extra", "fifth"]) == ["ai", "webdev", "python", "extra"]


def test_devto_payload_uses_canonical_url(settings) -> None:
    payload = devto_payload(ARTICLE, settings)
    body = payload["article"]
    assert body["canonical_url"] == "https://example.test/posts/2026-01-01-hello"
    assert body["published"] is True
    assert len(body["tags"]) <= 4


def test_devto_payload_links_absolutely_and_is_branded() -> None:
    settings = replace(Settings(), site_url=SITE)
    body = devto_payload(ARTICLE, settings)["article"]
    assert body["canonical_url"] == CANONICAL
    # The syndicated body ends with the publication attribution, itself absolute.
    assert f"Read more on Upwire: {CANONICAL}" in body["body_markdown"]
    assert "Upwire" in body["description"]
    # Never a bare path: the relative form must not survive anywhere.
    assert "Read more on Upwire: /posts/" not in body["body_markdown"]


# --- Hashnode --------------------------------------------------------------


def test_hashnode_tags_have_name_and_slug() -> None:
    tags = hashnode_tags(["AI", "web dev", "web dev"])
    assert tags[0] == {"name": "AI", "slug": "ai"}
    assert tags[1] == {"name": "web dev", "slug": "web-dev"}
    assert len(tags) == 2


def test_hashnode_variables_shape() -> None:
    settings = replace(Settings(), site_url=SITE, hashnode_publication_id="pub-1")
    variables = hashnode_variables(ARTICLE, settings)
    body = variables["input"]["contentMarkdown"]
    assert variables["input"]["publicationId"] == "pub-1"
    assert variables["input"]["originalArticleURL"] == CANONICAL
    # The syndicated body keeps the article and gains the publication
    # attribution block, always with the absolute link.
    assert body.startswith("Body.")
    assert "Read more on Upwire" in body
    assert CANONICAL in body
    assert "Read more on Upwire: /posts/" not in body


# --- absolute URLs ---------------------------------------------------------


def test_post_url_is_absolute(settings) -> None:
    assert post_url(settings, "2026-01-01-hello") == "https://example.test/posts/2026-01-01-hello"


def test_post_url_refuses_to_build_a_relative_link() -> None:
    with pytest.raises(MissingSiteUrl, match="SITE_URL is not set"):
        post_url(Settings(), "2026-01-01-hello")


def test_outbound_builders_raise_rather_than_emit_a_relative_link() -> None:
    """Without SITE_URL every outbound template fails instead of posting /posts/..."""
    no_site = Settings()
    assert no_site.site_url == ""
    for build in (
        lambda: build_channel_message(ARTICLE, no_site),
        lambda: build_status(ARTICLE, no_site),
        lambda: devto_payload(ARTICLE, no_site),
        lambda: hashnode_variables(ARTICLE, no_site),
    ):
        with pytest.raises(MissingSiteUrl):
            build()


def test_bluesky_poster_surfaces_the_missing_site_url() -> None:
    configured = replace(Settings(), bluesky_handle="h.test", bluesky_app_password="pw")
    with pytest.raises(MissingSiteUrl):
        bluesky_poster(ARTICLE, configured)


def test_site_publisher_still_writes_without_site_url(settings, tmp_path) -> None:
    """The site target writes a file, so a missing origin must not fail the run."""
    no_site = replace(settings, site_url="", content_posts_dir=tmp_path / "posts")
    result = site_publisher(ARTICLE, no_site)
    assert result.ok is True
    assert result.url == ""
    assert (tmp_path / "posts" / "2026-01-01-hello.md").exists()


# --- Mastodon --------------------------------------------------------------


def test_mastodon_status_respects_limit(settings) -> None:
    status = build_status({"teaser": "x " * 1000, "slug": "s"}, settings, limit=500)
    assert grapheme_len(status) <= 500
    assert "example.test" in status


# --- Site ------------------------------------------------------------------


def test_frontmatter_is_machine_readable(settings) -> None:
    frontmatter = build_frontmatter(ARTICLE, date=None)
    assert frontmatter.startswith("---\n")
    assert "ai_assisted: true" in frontmatter
    assert "topic_id: 3" in frontmatter
    assert 'slug: "2026-01-01-hello"' in frontmatter
    assert "sources:" in frontmatter
