"""Clustering on the frozen fixtures and stable topic identity across days."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from src.analysis import topics as topics_mod
from src.analysis.cluster import centroid_of, cluster, cluster_sources
from src.analysis.score import score_clusters
from src.ingest.fixtures_loader import DEFAULT_SOURCES, load_fixtures

UTC = timezone.utc


@pytest.fixture
def all_items() -> list[dict]:
    fixtures = load_fixtures()
    return [item for source in DEFAULT_SOURCES for item in fixtures[source]]


def test_fixtures_produce_a_rich_cross_source_cluster(all_items, settings) -> None:
    """Acceptance: a top cluster with >= 3 items from >= 2 sources exists."""
    clusters = cluster(all_items, threshold=settings.cluster_threshold)
    rich = [c for c in clusters if len(c) >= 3 and len(cluster_sources(c)) >= 2]
    assert rich, "fixtures must yield at least one rich cross-source cluster"
    biggest = max(rich, key=len)
    assert len(biggest) >= 3
    assert len(cluster_sources(biggest)) >= 2


def test_every_fixture_item_lands_in_exactly_one_cluster(all_items, settings) -> None:
    clusters = cluster(all_items, threshold=settings.cluster_threshold)
    total = sum(len(c) for c in clusters)
    assert total == len(all_items)


def test_topic_identity_is_stable_across_days(conn, settings, all_items) -> None:
    clusters = cluster(all_items, threshold=settings.cluster_threshold)
    rich = max(clusters, key=len)
    day1 = datetime(2026, 1, 1, tzinfo=UTC)
    day2 = day1 + timedelta(days=1)

    first = score_clusters(conn, [rich], all_items, settings, now=day1)[0]
    assert first["is_new"] is True
    topic_id = first["topic_id"]

    second = score_clusters(conn, [rich], all_items, settings, now=day2)[0]
    assert second["topic_id"] == topic_id
    assert second["is_new"] is False
    # Same size as yesterday → velocity is 1.0, not the old "no history" default.
    assert second["velocity"] == pytest.approx(1.0)
    assert second["history_days"] == 1


def test_dissimilar_cluster_gets_a_new_topic(conn, settings, all_items) -> None:
    clusters = cluster(all_items, threshold=settings.cluster_threshold)
    rich = max(clusters, key=len)
    rich_centroid = centroid_of(rich)

    other = None
    for candidate in sorted(clusters, key=len, reverse=True):
        if candidate is rich or not candidate:
            continue
        if float(np.dot(rich_centroid, centroid_of(candidate))) < 0.5:
            other = candidate
            break
    assert other is not None, "fixtures should contain an unrelated cluster"

    day1 = datetime(2026, 1, 1, tzinfo=UTC)
    first = score_clusters(conn, [rich], all_items, settings, now=day1)[0]
    day2 = day1 + timedelta(days=1)
    second = score_clusters(conn, [other], all_items, settings, now=day2)[0]
    assert second["topic_id"] != first["topic_id"]
    assert second["is_new"] is True


def test_clusters_in_one_run_get_distinct_topics(conn, settings, all_items) -> None:
    clusters = cluster(all_items, threshold=settings.cluster_threshold)[:5]
    ranked = score_clusters(conn, clusters, all_items, settings, now=datetime(2026, 3, 1, tzinfo=UTC))
    topic_ids = [row["topic_id"] for row in ranked]
    assert len(set(topic_ids)) == len(topic_ids)


def test_topics_are_pruned_after_retention(conn, settings, all_items) -> None:
    clusters = cluster(all_items, threshold=settings.cluster_threshold)
    rich = max(clusters, key=len)
    day1 = datetime(2026, 1, 1, tzinfo=UTC)
    score_clusters(conn, [rich], all_items, settings, now=day1)

    # 100 days later the topic is older than the 60-day retention window.
    later = day1 + timedelta(days=100)
    assert topics_mod.prune(conn, settings, now=later) >= 1
    assert conn.execute("SELECT COUNT(*) FROM topics").fetchone()[0] == 0
