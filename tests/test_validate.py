"""LLM response parsing and article validation."""

from __future__ import annotations

import json

from src.generate.draft_article import is_declined, parse_draft
from src.generate.validate import (
    build_sources_section,
    extract_urls,
    finalize_article,
    normalise_url,
    validate_article,
)

SOURCES = [
    {"title": "One", "url": "https://a.test/1", "source": "hackernews", "content": "c"},
    {"title": "Two", "url": "https://b.test/2", "source": "arxiv", "content": "c"},
]


def make_article(body_urls: list[str] | None = None, words: int = 450, title: str = "A grounded title", tags=None):
    urls = body_urls if body_urls is not None else [s["url"] for s in SOURCES]
    filler = " ".join(f"word{i}" for i in range(words - len(urls)))
    body = f"{filler} {' '.join(urls)}".strip()
    return {
        "title": title,
        "body_markdown": body,
        "teaser": "A short teaser.",
        "tags": tags if tags is not None else ["ai", "research"],
    }


# --- parsing ---------------------------------------------------------------


def test_parse_plain_json() -> None:
    parsed = parse_draft('{"title":"t","body_markdown":"b","teaser":"x","tags":["a"]}')
    assert parsed == {"title": "t", "body_markdown": "b", "teaser": "x", "tags": ["a"]}


def test_parse_fenced_json() -> None:
    text = '```json\n{"title":"t","body_markdown":"b","teaser":"x","tags":[]}\n```'
    assert parse_draft(text)["title"] == "t"


def test_parse_malformed_returns_none() -> None:
    assert parse_draft("this is not json at all") is None


def test_parse_empty_string_returns_none() -> None:
    assert parse_draft("") is None


def test_parse_tags_as_string_is_coerced() -> None:
    parsed = parse_draft('{"title":"t","body_markdown":"b","teaser":"x","tags":"ai"}')
    assert parsed["tags"] == ["ai"]


def test_empty_json_is_a_decline() -> None:
    parsed = parse_draft(json.dumps({"title": "", "body_markdown": "", "teaser": "", "tags": []}))
    assert is_declined(parsed) is True


def test_real_draft_is_not_a_decline() -> None:
    assert is_declined(make_article()) is False


# --- validation ------------------------------------------------------------


def test_valid_article_passes(settings) -> None:
    result = validate_article(make_article(), SOURCES, settings, existing_titles=set())
    assert result.ok, result.errors


def test_foreign_url_is_rejected(settings) -> None:
    article = make_article(body_urls=["https://a.test/1", "https://b.test/2", "https://evil.test/x"])
    result = validate_article(article, SOURCES, settings)
    assert not result.ok
    assert any("not in the supplied sources" in error for error in result.errors)


def test_url_normalisation_ignores_trailing_slash(settings) -> None:
    article = make_article(body_urls=["https://a.test/1/", "https://b.test/2"])
    assert validate_article(article, SOURCES, settings).ok


def test_placeholder_text_is_rejected(settings) -> None:
    article = make_article(words=460)
    article["body_markdown"] = article["body_markdown"].replace("word5", "[TODO]")
    result = validate_article(article, SOURCES, settings)
    assert not result.ok
    assert any("placeholder" in error for error in result.errors)


def test_as_an_ai_boilerplate_is_rejected(settings) -> None:
    article = make_article()
    article["body_markdown"] = f"As an AI, {article['body_markdown']}"
    result = validate_article(article, SOURCES, settings)
    assert any("as an ai" in error for error in result.errors)


def test_too_short_body_is_rejected(settings) -> None:
    result = validate_article(make_article(words=50), SOURCES, settings)
    assert not result.ok
    assert any("below the minimum" in error for error in result.errors)


def test_too_long_body_is_rejected(settings) -> None:
    result = validate_article(make_article(words=2000), SOURCES, settings)
    assert not result.ok
    assert any("above the maximum" in error for error in result.errors)


def test_overlong_title_is_rejected(settings) -> None:
    result = validate_article(make_article(title="x" * 200), SOURCES, settings)
    assert any("title is" in error for error in result.errors)


def test_unsafe_tags_are_rejected(settings) -> None:
    result = validate_article(make_article(tags=["Not Safe", "ok-tag"]), SOURCES, settings)
    assert any("not slug-safe" in error for error in result.errors)


def test_missing_tags_are_rejected(settings) -> None:
    result = validate_article(make_article(tags=[]), SOURCES, settings)
    assert any("tags must be a non-empty list" in error for error in result.errors)


def test_duplicate_title_is_rejected(settings) -> None:
    result = validate_article(make_article(title="Seen Before"), SOURCES, settings, existing_titles={"seen before"})
    assert any("duplicates" in error for error in result.errors)


def test_missing_fields_are_reported(settings) -> None:
    result = validate_article({}, SOURCES, settings)
    assert len(result.errors) >= 3


def test_feedback_text_mentions_each_error(settings) -> None:
    result = validate_article(make_article(words=10), SOURCES, settings)
    feedback = result.as_feedback()
    assert "rejected" in feedback
    for error in result.errors:
        assert error in feedback


# --- sources section -------------------------------------------------------


def test_finalize_appends_code_built_sources(settings) -> None:
    article = make_article()
    final = finalize_article(article, SOURCES)
    assert "## Sources" in final["body_markdown"]
    assert "https://a.test/1" in final["body_markdown"]
    assert final["sources"][0]["url"] == "https://a.test/1"
    assert final["body_markdown"].startswith(article["body_markdown"])


def test_build_sources_section_escapes_brackets() -> None:
    section = build_sources_section([{"title": "[Weird] title", "url": "u", "source": "s"}])
    assert "[Weird] title" not in section
    assert "(Weird) title" in section


def test_extract_and_normalise_urls() -> None:
    text = "see https://x.test/a. and https://y.test/b/"
    assert extract_urls(text) == ["https://x.test/a", "https://y.test/b"]
    assert normalise_url("https://X.test/A/") == "https://x.test/A"
