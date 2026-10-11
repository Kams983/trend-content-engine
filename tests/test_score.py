"""Scoring, eligibility, cooldown and determinism."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.analysis.cluster import cluster, cluster_sources
from src.analysis.score import engagement_percentiles, in_cooldown, score_clusters, velocity_for
from src.analysis.topics import centroid_of, encode_centroid
from src.ingest.fixtures_loader import DEFAULT_SOURCES, load_fixtures
from src.state import repo
from src.state.db import connect, init_db

UTC = timezone.utc
DAY1 = datetime(2026, 1, 1, tzinfo=UTC)


@pytest.fixture
def all_items() -> list[dict]:
    fixtures = load_fixtures()
    return [item for source in DEFAULT_SOURCES for item in fixtures[source]]


@pytest.fixture
def rich_and_singleton(all_items):
    clusters = cluster(all_items, threshold=0.40)
    rich = max([c for c in clusters if len(c) >= 3 and len(cluster_sources(c)) >= 2], key=len)
    singleton = max((c for c in clusters if len(c) == 1), key=lambda c: len(c[0].get("content", "")))
    return rich, singleton


def test_singleton_never_outranks_rich_cross_source_cluster(conn, settings, all_items, rich_and_singleton) -> None:
    rich, singleton = rich_and_singleton
    ranked = score_clusters(conn, [singleton, rich], all_items, settings, now=DAY1)
    top, bottom = ranked[0], ranked[-1]
    assert top["count"] >= 3 and len(top["sources"]) >= 2
    assert top["score"] > bottom["score"]
    assert bottom["count"] == 1
    assert bottom["eligible"] is False
    assert bottom["ineligibility_reason"] == "too_few_items"


def test_sources_term_rewards_diversity(conn, settings, all_items, rich_and_singleton) -> None:
    rich, _ = rich_and_singleton
    # Same cluster, but pretend it only came from one source.
    single_source = [{**item, "source": "hackernews"} for item in rich]
    ranked = score_clusters(conn, [single_source], all_items, settings, now=DAY1)[0]
    assert ranked["ineligibility_reason"] == "too_few_sources"


def test_eligibility_requires_min_items_and_sources(conn, settings, all_items, rich_and_singleton) -> None:
    rich, _ = rich_and_singleton
    ranked = score_clusters(conn, [rich], all_items, settings, now=DAY1)[0]
    assert ranked["eligible"] is True
    assert ranked["ineligibility_reason"] == ""


def test_score_is_deterministic(settings, all_items, rich_and_singleton) -> None:
    rich, singleton = rich_and_singleton
    snapshots = []
    for index in range(2):
        path = settings.db_path.parent / f"determinism-{index}.sqlite"
        conn = init_db(path)
        ranked = score_clusters(conn, [rich, singleton], all_items, settings, now=DAY1)
        snapshots.append([(row["label"], row["score"], row["count"], row["topic_id"]) for row in ranked])
        conn.close()
    assert snapshots[0] == snapshots[1]


def test_engagement_percentile_is_per_source() -> None:
    items = [
        {"source": "hackernews", "url": "a", "engagement": 10},
        {"source": "hackernews", "url": "b", "engagement": 100},
        {"source": "arxiv", "url": "c", "engagement": 1},
        {"source": "arxiv", "url": "d", "engagement": 2},
    ]
    percentiles = engagement_percentiles(items)
    # HN's 100 wins within HN; arXiv's 2 wins within arXiv.
    assert percentiles[("hackernews", "b")] > percentiles[("hackernews", "a")]
    assert percentiles[("arxiv", "d")] > percentiles[("arxiv", "c")]
    assert percentiles[("arxiv", "d")] == percentiles[("hackernews", "b")]


def test_velocity_defaults_to_one_without_history(conn, settings) -> None:
    velocity, days = velocity_for(conn, topic_id=999, today_count=5, settings=settings, now=DAY1)
    assert velocity == 1.0
    assert days == 0


def test_velocity_uses_topic_history(conn, settings) -> None:
    for offset in range(1, 4):
        repo.record_observation(
            conn,
            topic_id=1,
            day=(DAY1 - timedelta(days=offset)).strftime("%Y-%m-%d"),
            item_count=5,
            source_count=1,
            sources="hn",
        )
    velocity, days = velocity_for(conn, topic_id=1, today_count=10, settings=settings, now=DAY1)
    assert days == 3
    assert velocity == pytest.approx(2.0)


def _topic_for_cluster(conn, cluster_items):
    centroid = centroid_of(cluster_items)
    return repo.insert_topic(conn, centroid=encode_centroid(centroid), dim=len(centroid), label="x", when=DAY1.isoformat())


def test_cooldown_blocks_a_recently_published_topic(conn, settings, all_items, rich_and_singleton) -> None:
    rich, _ = rich_and_singleton
    topic_id = _topic_for_cluster(conn, rich)
    article_id = repo.insert_article(
        conn, slug="s", title="T", teaser="", body="b", topic_id=topic_id, cluster_label="", sources=[], tags=[]
    )
    repo.mark_published(conn, article_id, when=DAY1.isoformat())

    later = DAY1 + timedelta(days=1)
    assert in_cooldown(conn, topic_id, settings, now=later) is True
    ranked = score_clusters(conn, [rich], all_items, settings, now=later)[0]
    assert ranked["topic_id"] == topic_id
    assert ranked["eligible"] is False
    assert ranked["ineligibility_reason"] == "cooldown"


def test_cooldown_is_overridden_by_high_velocity(conn, settings, all_items, rich_and_singleton) -> None:
    rich, _ = rich_and_singleton
    topic_id = _topic_for_cluster(conn, rich)
    article_id = repo.insert_article(
        conn, slug="s", title="T", teaser="", body="b", topic_id=topic_id, cluster_label="", sources=[], tags=[]
    )
    repo.mark_published(conn, article_id, when=DAY1.isoformat())
    # A single prior item yesterday → today's count (12) means velocity 12.
    repo.record_observation(
        conn, topic_id=topic_id, day=DAY1.strftime("%Y-%m-%d"), item_count=1, source_count=1, sources="hn"
    )

    later = DAY1 + timedelta(days=1)
    ranked = score_clusters(conn, [rich], all_items, settings, now=later)[0]
    assert ranked["velocity"] >= settings.cooldown_velocity_override
    assert ranked["eligible"] is True


def test_cooldown_expires(conn, settings, all_items, rich_and_singleton) -> None:
    rich, _ = rich_and_singleton
    topic_id = _topic_for_cluster(conn, rich)
    article_id = repo.insert_article(
        conn, slug="s", title="T", teaser="", body="b", topic_id=topic_id, cluster_label="", sources=[], tags=[]
    )
    repo.mark_published(conn, article_id, when=DAY1.isoformat())
    later = DAY1 + timedelta(days=settings.cooldown_days + 1)
    assert in_cooldown(conn, topic_id, settings, now=later) is False


def test_observations_are_recorded_for_every_cluster(conn, settings, all_items, rich_and_singleton) -> None:
    rich, singleton = rich_and_singleton
    score_clusters(conn, [rich, singleton], all_items, settings, now=DAY1)
    topic_ids = [row["topic_id"] for row in conn.execute("SELECT DISTINCT topic_id FROM topic_observations")]
    assert len(topic_ids) == 2
