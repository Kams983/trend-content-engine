"""Normalisation of raw source items into the common schema."""

from __future__ import annotations

from datetime import datetime, timezone

from src.ingest.normalize import normalize

REQUIRED = {"source", "title", "content", "url", "engagement", "timestamp", "tags"}


def test_hackernews_normalized() -> None:
    raw = [{"id": 1, "time": 1700000000, "title": "A story", "score": 42, "text": "<p>body</p>", "type": "story"}]
    items = normalize(raw, "hackernews")
    assert len(items) == 1
    item = items[0]
    assert REQUIRED <= set(item)
    assert item["source"] == "hackernews"
    assert item["engagement"] == 42
    assert item["content"] == "body"  # HTML stripped
    assert item["timestamp"].tzinfo is not None


def test_hackernews_falls_back_to_item_url() -> None:
    raw = [{"id": 99, "time": 1700000000, "title": "No url", "score": 1}]
    items = normalize(raw, "hackernews")
    assert items[0]["url"] == "https://news.ycombinator.com/item?id=99"


def test_arxiv_normalized() -> None:
    raw = [
        {
            "title": "Paper",
            "summary": "abstract",
            "url": "http://arxiv.org/abs/1",
            "published": "2026-08-28T17:59:47Z",
            "authors": ["A", "B"],
            "categories": ["cs.LG"],
        }
    ]
    item = normalize(raw, "arxiv")[0]
    assert item["engagement"] == 2
    assert item["tags"] == ["cs.LG"]
    assert item["timestamp"].year == 2026


def test_github_normalized_merges_language_and_license() -> None:
    raw = [
        {
            "full_name": "a/b",
            "description": "desc",
            "html_url": "https://github.com/a/b",
            "stargazers_count": 100,
            "created_at": "2026-08-27T14:20:58Z",
            "topics": ["python"],
            "language": "Rust",
            "license": "MIT",
        }
    ]
    item = normalize(raw, "github_trending")[0]
    assert item["source"] == "github_trending"
    assert item["engagement"] == 100
    assert item["tags"] == ["python", "Rust", "MIT"]


def test_reddit_has_zero_engagement() -> None:
    raw = [{"title": "t", "url": "u", "updated": "2026-05-23T13:54:37Z", "content": "<div>x</div>"}]
    item = normalize(raw, "reddit")[0]
    assert item["engagement"] == 0
    assert item["content"] == "x"


def test_items_without_title_are_dropped() -> None:
    raw = [{"title": "", "url": "u"}, {"title": "kept", "url": "u2"}]
    items = normalize(raw, "reddit")
    assert [i["title"] for i in items] == ["kept"]


def test_unknown_source_passes_through() -> None:
    raw = [{"whatever": 1}]
    assert normalize(raw, "mystery") == raw


def test_bad_timestamp_falls_back_to_now() -> None:
    raw = [{"title": "t", "url": "u", "published": "not-a-date"}]
    item = normalize(raw, "arxiv")[0]
    assert (datetime.now(timezone.utc) - item["timestamp"]).total_seconds() < 5
