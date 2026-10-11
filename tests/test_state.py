"""Migrations, repository helpers and the publications idempotency guard."""

from __future__ import annotations

import sqlite3

from src.state import repo
from src.state.db import connect, init_db, migrate


def test_migrate_is_idempotent(settings) -> None:
    conn = connect(settings.db_path)
    first = migrate(conn)
    second = migrate(conn)
    assert isinstance(first, list)
    assert second == []  # nothing left to add
    conn.close()


def test_migrate_upgrades_legacy_tables_without_data_loss(tmp_path) -> None:
    path = tmp_path / "legacy.sqlite"
    legacy = sqlite3.connect(str(path))
    # The pre-hardening schema: run_log has no outcome/reason, topic_history
    # has no topic_id.
    legacy.executescript(
        """
        CREATE TABLE run_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            trend TEXT NOT NULL,
            source TEXT NOT NULL,
            item_count INTEGER NOT NULL,
            site_ok INTEGER NOT NULL,
            bluesky_ok INTEGER NOT NULL,
            telegram_ok INTEGER NOT NULL
        );
        CREATE TABLE topic_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            topic TEXT NOT NULL,
            source TEXT NOT NULL,
            item_count INTEGER NOT NULL,
            timestamp TEXT NOT NULL
        );
        INSERT INTO run_log (timestamp, trend, source, item_count, site_ok, bluesky_ok, telegram_ok)
            VALUES ('2026-01-01T00:00:00+00:00', 'old trend', 'hn', 3, 1, 1, 1);
        INSERT INTO topic_history (topic, source, item_count, timestamp)
            VALUES ('old label', 'hn', 3, '2026-01-01T00:00:00+00:00');
        """
    )
    legacy.commit()
    legacy.close()

    conn = connect(path)
    added = migrate(conn)
    assert "run_log.outcome" in added
    assert "topic_history.topic_id" in added

    columns = {row[1] for row in conn.execute("PRAGMA table_info(run_log)")}
    assert {"outcome", "reason", "stage", "details"} <= columns

    # Old rows survive untouched.
    assert conn.execute("SELECT COUNT(*) FROM run_log").fetchone()[0] == 1
    assert repo.legacy_topic_history_count(conn) == 1
    # And the migrated row is still readable through the new column.
    assert conn.execute("SELECT outcome FROM run_log").fetchone()[0] == ""
    conn.close()


def test_init_db_creates_all_tables(settings) -> None:
    conn = init_db(settings.db_path)
    names = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"run_log", "articles", "publications", "topics", "topic_observations", "topic_history"} <= names
    conn.close()


def test_record_run_stores_outcome_and_reason(conn) -> None:
    from src.outcomes import Outcome

    repo.record_run(conn, outcome=Outcome.PENDING_APPROVAL, reason="awaiting", stage="draft")
    row = repo.last_runs(conn, limit=1)[0]
    assert row["outcome"] == "PENDING_APPROVAL"
    assert row["reason"] == "awaiting"
    assert row["stage"] == "draft"


def test_article_lifecycle_and_slug_collision(conn) -> None:
    article_id = repo.insert_article(
        conn,
        slug="2026-01-01-hello",
        title="Hello",
        teaser="t",
        body="b",
        topic_id=1,
        cluster_label="l",
        sources=[{"title": "s", "url": "u"}],
        tags=["x"],
    )
    assert repo.slug_exists(conn, "2026-01-01-hello")
    assert repo.get_article(conn, article_id)["status"] == repo.STATUS_PENDING
    assert repo.existing_titles(conn) == {"hello"}
    assert repo.article_sources(conn, repo.get_article(conn, article_id)) == [{"title": "s", "url": "u"}]
    assert repo.article_tags(conn, repo.get_article(conn, article_id)) == ["x"]


def test_publications_are_idempotent(conn) -> None:
    article_id = repo.insert_article(
        conn, slug="s", title="T", teaser="", body="b", topic_id=None, cluster_label="", sources=[], tags=[]
    )
    first = repo.record_publication(conn, article_id=article_id, target="site", status=repo.PUB_OK, url="u")
    second = repo.record_publication(conn, article_id=article_id, target="site", status=repo.PUB_OK, url="u")
    assert first is True
    assert second is False  # the unique (article_id, target) index blocked it
    assert len(repo.publications_for(conn, article_id)) == 1
    assert repo.get_publication(conn, article_id, "site")["url"] == "u"


def test_mark_published_and_cooldown_lookup(conn) -> None:
    article_id = repo.insert_article(
        conn, slug="s2", title="T2", teaser="", body="b", topic_id=7, cluster_label="", sources=[], tags=[]
    )
    assert repo.last_published_at(conn, 7) is None
    repo.mark_published(conn, article_id, when="2026-01-01T00:00:00+00:00")
    assert repo.get_article(conn, article_id)["status"] == repo.STATUS_PUBLISHED
    assert repo.last_published_at(conn, 7) == "2026-01-01T00:00:00+00:00"


def test_observation_counts_window(conn) -> None:
    for day, count in (("2026-01-01", 2), ("2026-01-02", 4), ("2026-01-03", 6)):
        repo.record_observation(conn, topic_id=1, day=day, item_count=count, source_count=1, sources="hn")
    counts = repo.observation_counts(conn, 1, "2026-01-01", before_day="2026-01-03")
    assert counts == [2, 4]


def test_observation_upsert_is_rerun_safe(conn) -> None:
    repo.record_observation(conn, topic_id=1, day="2026-01-01", item_count=2, source_count=1, sources="hn")
    repo.record_observation(conn, topic_id=1, day="2026-01-01", item_count=5, source_count=2, sources="hn,rd")
    assert repo.observation_counts(conn, 1, "2026-01-01") == [5]


def test_prune_topics_removes_old_ones(conn) -> None:
    repo.insert_topic(conn, centroid=b"\x00\x00\x00\x00", dim=1, label="old", when="2020-01-01T00:00:00+00:00")
    repo.insert_topic(conn, centroid=b"\x00\x00\x00\x00", dim=1, label="new", when="2030-01-01T00:00:00+00:00")
    removed = repo.prune_topics(conn, "2026-01-01T00:00:00+00:00")
    assert removed == 1
    assert [row["label"] for row in repo.topics_since(conn, "2000-01-01T00:00:00+00:00")] == ["new"]
