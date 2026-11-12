"""Per-source trust weights from traffic, and their effect on scoring."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.analysis.score import score_clusters
from src.learn import feedback
from src.state import repo
from src.state.db import init_db

UTC = timezone.utc
NOW = datetime(2026, 11, 9, 12, 0, tzinfo=UTC)


def publish(conn, slug: str, sources: list[str], *, when: datetime | None = None) -> int:
    """Insert a post with *sources* and mark it published at *when*."""
    when = when or NOW
    article_id = repo.insert_article(
        conn,
        slug=slug,
        title=f"Post {slug}",
        teaser="A teaser.",
        body="A body.",
        topic_id=None,
        cluster_label="a trend",
        sources=[
            {"title": f"item from {source}", "url": f"https://example.test/{source}", "source": source}
            for source in sources
        ],
        tags=["ai"],
        status=repo.STATUS_PENDING,
        created_at=when.isoformat(),
    )
    repo.mark_published(conn, article_id, when=when.isoformat())
    return article_id


# ---------------------------------------------------------------------------
# Traffic input
# ---------------------------------------------------------------------------


def test_missing_traffic_file_is_no_data(tmp_path) -> None:
    assert feedback.load_traffic(tmp_path / "absent.json") == {}


def test_traffic_ignores_malformed_values(tmp_path) -> None:
    path = tmp_path / "traffic.json"
    path.write_text('{"a": 5, "b": "lots", "c": -3, "d": 2.9}', encoding="utf-8")
    assert feedback.load_traffic(path) == {"a": 5, "c": 0, "d": 2}


# ---------------------------------------------------------------------------
# Weight computation
# ---------------------------------------------------------------------------


def test_views_are_split_across_a_posts_sources(conn) -> None:
    publish(conn, "post-a", ["hackernews", "arxiv"], when=NOW - timedelta(days=1))
    publish(conn, "post-b", ["hackernews"], when=NOW - timedelta(days=2))

    weights = feedback.source_trust(conn, {"post-a": 100, "post-b": 100}, now=NOW)

    # hn: (50 + 100) over 2 posts = 75; arxiv: 50 over 1 post = 50; window mean 100.
    assert weights["hackernews"] == pytest.approx(0.75)
    assert weights["arxiv"] == pytest.approx(0.5)


def test_read_source_is_boosted_and_ignored_source_damped(conn) -> None:
    publish(conn, "read", ["hackernews"], when=NOW - timedelta(days=1))
    publish(conn, "ignored", ["arxiv"], when=NOW - timedelta(days=2))

    weights = feedback.source_trust(conn, {"read": 100}, now=NOW)

    assert weights["hackernews"] == feedback.MAX_WEIGHT
    assert weights["arxiv"] == feedback.MIN_WEIGHT


def test_posts_outside_the_window_are_ignored(conn) -> None:
    publish(conn, "old", ["hackernews"], when=NOW - timedelta(days=60))
    publish(conn, "new", ["arxiv"], when=NOW - timedelta(days=1))

    weights = feedback.source_trust(conn, {"old": 10_000, "new": 10}, now=NOW)

    assert "hackernews" not in weights
    assert weights["arxiv"] == pytest.approx(1.0)


def test_no_views_means_neutral_weights(conn) -> None:
    publish(conn, "unread", ["hackernews"], when=NOW - timedelta(days=1))
    assert feedback.source_trust(conn, {}, now=NOW) == {"hackernews": 1.0}


def test_unpublished_posts_are_ignored(conn) -> None:
    repo.insert_article(
        conn,
        slug="draft",
        title="Draft",
        teaser="t",
        body="b",
        topic_id=None,
        cluster_label="l",
        sources=[{"title": "s", "url": "https://example.test/s", "source": "hackernews"}],
        tags=["ai"],
        status=repo.STATUS_PENDING,
        created_at=NOW.isoformat(),
    )
    assert feedback.source_trust(conn, {"draft": 500}, now=NOW) == {}


def test_no_published_posts_yields_no_weights(conn) -> None:
    assert feedback.source_trust(conn, {"anything": 10}, now=NOW) == {}


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


def test_weights_round_trip_through_settings_yaml(tmp_path) -> None:
    path = tmp_path / "settings.yaml"
    feedback.write_weights(
        {"hackernews": 1.234, "arxiv": 0.876}, path=path, window_days=30, articles_considered=4, now=NOW
    )

    text = path.read_text(encoding="utf-8")
    assert "source_trust:" in text
    assert "generated_at:" in text
    assert feedback.load_weights(path) == {"hackernews": 1.234, "arxiv": 0.876}
    assert feedback.load_weights(tmp_path / "absent.yaml") == {}


def test_trust_for_averages_known_sources_and_defaults_to_neutral() -> None:
    weights = {"hackernews": 1.5, "arxiv": 0.5}

    assert feedback.trust_for(["hackernews", "arxiv"], weights) == pytest.approx(1.0)
    assert feedback.trust_for(["hackernews", "unknown"], weights) == pytest.approx(1.25)
    assert feedback.trust_for([], weights) == 1.0
    assert feedback.trust_for(["hackernews"], {}) == 1.0


def test_cli_writes_the_weights_file(conn, settings, tmp_path) -> None:
    publish(conn, "post", ["hackernews"], when=NOW - timedelta(days=1))
    traffic = tmp_path / "traffic.json"
    traffic.write_text('{"post": 40}', encoding="utf-8")
    out = tmp_path / "out.yaml"

    code = feedback.main(["--traffic", str(traffic), "--out", str(out), "--db", str(settings.db_path)])

    assert code == 0
    assert feedback.load_weights(out) == {"hackernews": 1.0}


# ---------------------------------------------------------------------------
# Scoring integration
# ---------------------------------------------------------------------------


def test_score_multiplies_by_source_trust(settings, tmp_path, monkeypatch) -> None:
    items = [
        {"source": "hackernews", "title": "Rust rewrites of office suites", "content": "a" * 60,
         "url": "https://example.test/1", "engagement": 10},
        {"source": "arxiv", "title": "Rust rewrites of office suites", "content": "a" * 60,
         "url": "https://example.test/2", "engagement": 5},
    ]

    conn_before = init_db(tmp_path / "neutral.sqlite")
    neutral = score_clusters(conn_before, [items], items, settings, now=NOW)[0]
    conn_before.close()
    assert neutral["source_trust"] == 1.0

    path = tmp_path / "weights.yaml"
    feedback.write_weights({"hackernews": 1.5, "arxiv": 1.5}, path=path, now=NOW)
    monkeypatch.setenv("SOURCE_WEIGHTS_PATH", str(path))

    conn_after = init_db(tmp_path / "trusted.sqlite")
    boosted = score_clusters(conn_after, [items], items, settings, now=NOW)[0]
    conn_after.close()

    assert boosted["source_trust"] == 1.5
    assert boosted["score"] == pytest.approx(neutral["score"] * 1.5, rel=0.01)
