"""Text helpers: slugify, graphemes, HTML stripping and JSON extraction."""

from __future__ import annotations

import pytest

from src.util.text import (
    count_words,
    extract_json_object,
    grapheme_len,
    slugify,
    slugify_unique,
    strip_html,
    truncate_graphemes,
)


def test_slugify_basic() -> None:
    assert slugify("How to Build a Diffusion Language Model!") == "how-to-build-a-diffusion-language-model"


def test_slugify_collapses_and_trims() -> None:
    assert slugify("  ***Hello---World***  ") == "hello-world"


def test_slugify_empty_falls_back() -> None:
    assert slugify("") == "untitled"
    assert slugify("!!!") == "untitled"


def test_slugify_strips_accents() -> None:
    assert slugify("Café Naïve") == "cafe-naive"


def test_slugify_unique_appends_counter() -> None:
    taken = {"hello-world"}
    assert slugify_unique("Hello World", taken) == "hello-world-2"
    taken.add("hello-world-2")
    assert slugify_unique("Hello World", taken) == "hello-world-3"


def test_count_words() -> None:
    assert count_words("one two three") == 3
    assert count_words("") == 0


def test_grapheme_len_counts_family_emoji_as_one() -> None:
    family = "👨‍👩‍👧"
    assert len(family) > 1
    assert grapheme_len(family) == 1
    assert grapheme_len("a" + family + "b") == 3


def test_truncate_graphemes_respects_limit() -> None:
    text = "👨‍👩‍👧" * 10
    result = truncate_graphemes(text, 4)
    assert grapheme_len(result) <= 4
    assert result.endswith("…")


def test_truncate_no_change_when_short() -> None:
    assert truncate_graphemes("short", 100) == "short"


def test_strip_html_removes_tags_and_entities() -> None:
    raw = "<p>Hello <b>World</b>&amp; friends</p>"
    stripped = strip_html(raw)
    assert stripped == "Hello World & friends"
    assert "<" not in stripped and ">" not in stripped


def test_strip_html_fast_path_unchanged() -> None:
    assert strip_html("plain text") == "plain text"


def test_extract_json_plain() -> None:
    assert extract_json_object('{"a": 1}') == {"a": 1}


def test_extract_json_fenced() -> None:
    text = '```json\n{"title": "x", "tags": ["a"]}\n```'
    assert extract_json_object(text) == {"title": "x", "tags": ["a"]}


def test_extract_json_with_prose_around_it() -> None:
    text = 'Sure, here you go:\n{"title": "x"}\nHope that helps!'
    assert extract_json_object(text) == {"title": "x"}


def test_extract_json_nested_braces_in_string() -> None:
    text = '{"body": "a { brace } inside", "n": 1}'
    assert extract_json_object(text) == {"body": "a { brace } inside", "n": 1}


@pytest.mark.parametrize("bad", ["", "not json", "{unclosed", "[1, 2, 3]", "null"])
def test_extract_json_returns_none_on_garbage(bad: str) -> None:
    assert extract_json_object(bad) is None
