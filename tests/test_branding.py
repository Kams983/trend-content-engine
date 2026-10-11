"""Branding guardrails: the engine name never reaches a reader.

The engine is the Trend Content Engine (TCE); everything a reader sees is the
publication brand (``BRAND_NAME`` / ``BRAND_TAGLINE``, default *Upwire*). These
tests hold that split in place:

* the brand is configurable and propagates to every public template at once,
* no outbound template (or draft prompt) can carry the engine name,
* the brand literal lives in exactly one Python module,
* the site build keeps its own guardrail wired up.
"""

from __future__ import annotations

import json
import re
from dataclasses import replace
from pathlib import Path

import pytest

from src.config import DEFAULT_BRAND_NAME, DEFAULT_BRAND_TAGLINE, load_settings
from src.generate.draft_article import load_system_prompt
from src.publish import preview_publication
from src.publish.base import (
    as_publication_article,
    attribution_line,
    compose_post_text,
    cross_post_body,
    publication_footer,
)
from src.publish.bluesky_poster import BLUESKY_LIMIT, build_post_text
from src.publish.devto_poster import build_payload as devto_payload
from src.publish.hashnode_poster import build_variables as hashnode_variables
from src.publish.mastodon_poster import build_status
from src.publish.telegram_poster import build_channel_message
from src.util.text import grapheme_len

#: The internal name. Reader-facing output must never contain it.
ENGINE_NAME = "Trend Content Engine"

REPO_ROOT = Path(__file__).resolve().parents[1]

ARTICLE = {
    "slug": "2026-01-01-branding",
    "title": "A grounded headline",
    "teaser": "A short teaser about the trend.",
    "body_markdown": "Body paragraph.",
    "tags": ["ai", "research"],
    "topic_id": 7,
    "sources": [{"title": "S", "url": "https://a.test", "source": "hackernews"}],
}

REBRANDED = "Zeta Weekly"


def outbound_texts(settings) -> dict[str, str]:
    """Every reader-facing outbound template, rendered with *settings*."""
    return {
        "bluesky": build_post_text(
            ARTICLE["teaser"],
            "https://example.test/posts/x",
            footer=publication_footer(settings.brand_name),
        ),
        "mastodon": build_status(ARTICLE, settings),
        "telegram": build_channel_message(ARTICLE, settings),
        "devto-description": devto_payload(ARTICLE, settings)["article"]["description"],
        "devto-body": devto_payload(ARTICLE, settings)["article"]["body_markdown"],
        "hashnode-body": hashnode_variables(ARTICLE, settings)["input"]["contentMarkdown"],
        "preview": preview_publication(ARTICLE, settings, "bluesky"),
    }


# --- the setting itself ----------------------------------------------------


def test_the_engine_name_is_not_the_default_brand() -> None:
    assert DEFAULT_BRAND_NAME.strip()
    assert DEFAULT_BRAND_NAME != ENGINE_NAME
    assert ENGINE_NAME not in DEFAULT_BRAND_NAME
    assert ENGINE_NAME not in DEFAULT_BRAND_TAGLINE


def test_brand_defaults_are_the_documented_ones() -> None:
    assert DEFAULT_BRAND_NAME == "Upwire"
    assert DEFAULT_BRAND_TAGLINE == "What's rising in tech and AI, with sources."


def test_brand_is_configurable_from_the_environment(tmp_path, monkeypatch) -> None:
    env_file = tmp_path / "absent.env"
    default = load_settings(dry_run=True, use_fixtures=True, env_file=env_file)
    assert default.brand_name == DEFAULT_BRAND_NAME
    assert default.brand_tagline == DEFAULT_BRAND_TAGLINE

    monkeypatch.setenv("BRAND_NAME", REBRANDED)
    monkeypatch.setenv("BRAND_TAGLINE", "A different remit.")
    rebranded = load_settings(dry_run=True, use_fixtures=True, env_file=env_file)
    assert rebranded.brand_name == REBRANDED
    assert rebranded.brand_tagline == "A different remit."


def test_the_brand_literal_lives_in_one_python_module() -> None:
    """A rebrand must not require a code edit anywhere else."""
    offenders = []
    for path in (REPO_ROOT / "src").rglob("*.py"):
        if path.name == "config.py":
            continue
        text = path.read_text(encoding="utf-8")
        if DEFAULT_BRAND_NAME in text or DEFAULT_BRAND_TAGLINE in text:
            offenders.append(str(path.relative_to(REPO_ROOT)))
    assert offenders == []


# --- outbound templates ----------------------------------------------------


def test_no_outbound_template_can_carry_the_engine_name(settings) -> None:
    for name, text in outbound_texts(settings).items():
        assert ENGINE_NAME not in text, f"{name} leaked the engine name"
        assert "TCE" not in text, f"{name} leaked the engine acronym"


def test_every_outbound_template_carries_the_publication_brand(settings) -> None:
    for name, text in outbound_texts(settings).items():
        assert settings.brand_name in text, f"{name} is missing the publication brand"


def test_rebranding_changes_every_public_template_at_once(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("BRAND_NAME", REBRANDED)
    # Outbound templates need an origin: they must never carry a relative link.
    monkeypatch.setenv("SITE_URL", "https://upwire.example.test")
    rebranded = load_settings(dry_run=True, use_fixtures=True, env_file=tmp_path / "absent.env")
    for name, text in outbound_texts(rebranded).items():
        assert REBRANDED in text, f"{name} did not pick up the new brand"
        assert DEFAULT_BRAND_NAME not in text, f"{name} still shows the old brand"


def test_attribution_shape_is_shared_by_every_target() -> None:
    assert publication_footer("Upwire") == "Read more on Upwire"
    assert attribution_line("Upwire", "https://x.test/posts/a") == "Read more on Upwire: https://x.test/posts/a"


def test_an_empty_brand_degrades_cleanly() -> None:
    assert publication_footer("") == ""
    assert attribution_line("", "https://x.test/posts/a") == "https://x.test/posts/a"


def test_as_publication_article_adds_the_brand(settings) -> None:
    enriched = as_publication_article(ARTICLE, ARTICLE["slug"], settings)
    assert enriched["brand_name"] == settings.brand_name
    assert enriched["brand_tagline"] == settings.brand_tagline
    assert enriched["attribution"].startswith(f"Read more on {settings.brand_name}")


# --- short-form posts ------------------------------------------------------


def test_long_teaser_keeps_the_link_and_the_attribution_within_the_limit() -> None:
    teaser = "word " * 200
    text = compose_post_text(
        teaser, "https://example.test/posts/x", limit=BLUESKY_LIMIT, footer=publication_footer("Upwire")
    )
    assert grapheme_len(text) <= BLUESKY_LIMIT
    assert text.endswith("https://example.test/posts/x")
    assert "Read more on Upwire" in text


def test_attribution_is_dropped_before_the_link_when_the_budget_is_tight() -> None:
    # A link plus attribution that cannot both fit: the link must survive.
    url = "https://example.test/" + "a" * 60
    text = compose_post_text("teaser", url, limit=len(url) + 4, footer=publication_footer("Upwire"))
    assert url in text
    assert "Read more on Upwire" not in text


def test_short_post_without_a_link_is_just_the_teaser() -> None:
    assert compose_post_text("just a teaser", "") == "just a teaser"


# --- cross-posts -----------------------------------------------------------


def test_cross_post_body_ends_with_the_attribution_block() -> None:
    body = cross_post_body("Body.", "https://x.test/posts/a", "Upwire")
    assert body.startswith("Body.")
    assert body.rstrip().endswith("Read more on Upwire: https://x.test/posts/a")


def test_devto_payload_is_branded(settings) -> None:
    payload = devto_payload(ARTICLE, settings)["article"]
    assert settings.brand_name in payload["description"]
    assert settings.brand_name in payload["body_markdown"]
    assert payload["canonical_url"] == "https://example.test/posts/2026-01-01-branding"


def test_hashnode_body_is_branded(settings) -> None:
    payload = hashnode_variables(ARTICLE, settings)["input"]
    assert settings.brand_name in payload["contentMarkdown"]


# --- dry-run preview -------------------------------------------------------


def test_dry_run_preview_shows_the_brand(settings) -> None:
    preview = json.loads(preview_publication(ARTICLE, settings, "bluesky"))
    assert preview["brand"] == settings.brand_name
    assert settings.brand_name in preview["text"]
    assert ENGINE_NAME not in preview["text"]


# --- the drafting prompt ---------------------------------------------------


def test_system_prompt_names_the_publication_without_a_token(settings) -> None:
    prompt = load_system_prompt(settings)
    assert "{{publication}}" not in prompt
    assert "{{tagline}}" not in prompt
    assert settings.brand_name in prompt
    assert ENGINE_NAME not in prompt


def test_system_prompt_file_keeps_the_tokens() -> None:
    """The tokens are the contract; without them the model sees no publication."""
    raw = load_system_prompt()
    assert "{{publication}}" in raw
    assert "{{tagline}}" in raw


# --- committed content and the site build ----------------------------------


def test_committed_posts_never_name_the_engine() -> None:
    posts = sorted((REPO_ROOT / "site" / "content" / "posts").glob("*.md"))
    assert posts, "expected at least the hand-written welcome post"
    for post in posts:
        assert ENGINE_NAME not in post.read_text(encoding="utf-8")


def test_site_build_runs_the_brand_guardrail() -> None:
    package = json.loads((REPO_ROOT / "site" / "package.json").read_text(encoding="utf-8"))
    assert "check:brand" in package["scripts"]["build"]
    script = REPO_ROOT / "site" / "scripts" / "check-brand.mjs"
    assert script.exists()
    assert re.search(r"Trend\\s\+Content\\s\+Engine", script.read_text(encoding="utf-8"))


def test_site_identity_reads_the_public_brand_variables() -> None:
    site_ts = (REPO_ROOT / "site" / "src" / "lib" / "site.ts").read_text(encoding="utf-8")
    assert "import.meta.env.PUBLIC_BRAND_NAME" in site_ts
    assert "import.meta.env.PUBLIC_BRAND_TAGLINE" in site_ts
    assert "title: BRAND.name" in site_ts


@pytest.mark.parametrize("value", ["", "   "])
def test_a_blank_brand_falls_back_to_the_default(tmp_path, monkeypatch, value) -> None:
    """A blank name must not render an unnamed publication."""
    monkeypatch.setenv("BRAND_NAME", value)
    settings = load_settings(dry_run=True, use_fixtures=True, env_file=tmp_path / "absent.env")
    assert settings.brand_name == DEFAULT_BRAND_NAME
    assert settings.brand_name.strip()


def test_the_brand_is_stripped(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("BRAND_NAME", "  Upwire  ")
    settings = load_settings(dry_run=True, use_fixtures=True, env_file=tmp_path / "absent.env")
    assert settings.brand_name == DEFAULT_BRAND_NAME
