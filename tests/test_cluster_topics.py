"""Clustering on the frozen fixtures and stable topic identity across days."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from src.analysis import topics as topics_mod
from src.analysis.cluster import DEFAULT_THRESHOLD, centroid_of, cluster, cluster_sources
from src.analysis.embed import set_encoder
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


def _install_vectors(vectors: list[tuple[float, float]]) -> None:
    """Replace the encoder with fixed 2-d vectors, one per input text, in order."""
    matrix = np.array(vectors, dtype=np.float32)
    set_encoder(lambda texts: matrix[: len(texts)])


def _items(*titles: str) -> list[dict]:
    sources = ("hackernews", "arxiv", "reddit", "github_trending")
    return [
        {"title": t, "content": "", "source": sources[i % len(sources)], "url": f"https://example.test/{t}"}
        for i, t in enumerate(titles)
    ]


def test_similarity_chains_do_not_merge_unrelated_items() -> None:
    """A~B and B~C must not glue A to C: membership is judged on the centroid.

    Angles: A=0deg, B=50deg, C=100deg. sim(A,B)=sim(B,C)=0.64, sim(A,C)=-0.17,
    and C sits 75deg (sim 0.26) from the A+B centroid — well under the threshold.
    """
    _install_vectors([(1.0, 0.0), (0.643, 0.766), (-0.174, 0.985)])
    groups = cluster(_items("a", "b", "c"), threshold=DEFAULT_THRESHOLD)

    sizes = sorted(len(g) for g in groups)
    assert sizes == [1, 2], f"chain merged unrelated items: {sizes}"
    assert {it["title"] for it in max(groups, key=len)} == {"a", "b"}


def test_duplicates_and_near_duplicates_still_cluster() -> None:
    """The tighter threshold must not turn obvious repeats into singletons."""
    _install_vectors([(1.0, 0.0), (0.999, 0.04), (0.95, 0.31), (0.0, 1.0)])
    groups = cluster(_items("a", "b", "c", "unrelated"), threshold=DEFAULT_THRESHOLD)

    biggest = max(groups, key=len)
    assert {it["title"] for it in biggest} == {"a", "b", "c"}
    assert any(it["title"] == "unrelated" for g in groups for it in g if len(g) == 1)


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
