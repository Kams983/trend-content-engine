"""Publisher-specific behaviour: facets, graphemes, escaping and payloads."""

from __future__ import annotations

from dataclasses import replace

from src.config import Settings
from src.publish.bluesky_poster import BLUESKY_LIMIT, build_facets, build_post_text
from src.publish.devto_poster import build_payload as devto_payload, devto_tags
from src.publish.hashnode_poster import build_variables as hashnode_variables, hashnode_tags
from src.publish.mastodon_poster import build_status
from src.publish.site_publisher import build_frontmatter
from src.publish.telegram_poster import build_approval_keyboard, build_channel_message, escape_html
from src.util.text import grapheme_len

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


# --- Hashnode --------------------------------------------------------------


def test_hashnode_tags_have_name_and_slug() -> None:
    tags = hashnode_tags(["AI", "web dev", "web dev"])
    assert tags[0] == {"name": "AI", "slug": "ai"}
    assert tags[1] == {"name": "web dev", "slug": "web-dev"}
    assert len(tags) == 2


def test_hashnode_variables_shape() -> None:
    settings = replace(Settings(), hashnode_publication_id="pub-1")
    variables = hashnode_variables(ARTICLE, settings)
    assert variables["input"]["publicationId"] == "pub-1"
    assert variables["input"]["originalArticleURL"].endswith("/posts/2026-01-01-hello")
    assert variables["input"]["contentMarkdown"] == "Body."


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
