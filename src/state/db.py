"""SQLite schema and idempotent migrations.

``migrate()`` is safe to run on every start: it creates missing tables, adds
missing columns to pre-existing ones (so a database written by an older version
of the engine keeps working) and never drops data.

Tables
------
run_log              one row per run/stage with an explicit outcome + reason
articles             drafts awaiting approval and published articles
publications         one row per (article, target) — the idempotency guard
topics               centroid identity: stable topic_id → 384-d centroid blob
topic_observations   per-topic, per-day item/source counts (velocity history)
topic_history        LEGACY label-keyed table, preserved for audit, plus a
                     back-filled ``topic_id`` column
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

from ..util.logging_setup import kv

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 2

_SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS run_log (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp  TEXT    NOT NULL,
    trend      TEXT    NOT NULL DEFAULT '',
    source     TEXT    NOT NULL DEFAULT '',
    item_count INTEGER NOT NULL DEFAULT 0,
    site_ok    INTEGER NOT NULL DEFAULT 0,
    bluesky_ok INTEGER NOT NULL DEFAULT 0,
    telegram_ok INTEGER NOT NULL DEFAULT 0,
    outcome    TEXT    NOT NULL DEFAULT '',
    reason     TEXT    NOT NULL DEFAULT '',
    stage      TEXT    NOT NULL DEFAULT '',
    details    TEXT    NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS articles (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id        TEXT    NOT NULL DEFAULT '',
    slug          TEXT    NOT NULL,
    title         TEXT    NOT NULL,
    teaser        TEXT    NOT NULL DEFAULT '',
    body          TEXT    NOT NULL,
    topic_id      INTEGER,
    cluster_label TEXT    NOT NULL DEFAULT '',
    sources_json  TEXT    NOT NULL DEFAULT '[]',
    tags_json     TEXT    NOT NULL DEFAULT '[]',
    status        TEXT    NOT NULL DEFAULT 'pending_approval',
    created_at    TEXT    NOT NULL,
    published_at  TEXT
);

CREATE TABLE IF NOT EXISTS publications (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    article_id  INTEGER NOT NULL,
    target      TEXT    NOT NULL,
    status      TEXT    NOT NULL,
    external_id TEXT    NOT NULL DEFAULT '',
    url         TEXT    NOT NULL DEFAULT '',
    error       TEXT    NOT NULL DEFAULT '',
    created_at  TEXT    NOT NULL,
    UNIQUE (article_id, target)
);

CREATE TABLE IF NOT EXISTS topics (
    topic_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    centroid   BLOB    NOT NULL,
    dim        INTEGER NOT NULL,
    label      TEXT    NOT NULL DEFAULT '',
    first_seen TEXT    NOT NULL,
    last_seen  TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS topic_observations (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    topic_id     INTEGER NOT NULL,
    day          TEXT    NOT NULL,
    item_count   INTEGER NOT NULL,
    source_count INTEGER NOT NULL DEFAULT 0,
    sources      TEXT    NOT NULL DEFAULT '',
    timestamp    TEXT    NOT NULL,
    UNIQUE (topic_id, day)
);

CREATE TABLE IF NOT EXISTS topic_history (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    topic      TEXT    NOT NULL,
    source     TEXT    NOT NULL,
    item_count INTEGER NOT NULL,
    timestamp  TEXT    NOT NULL,
    topic_id   INTEGER
);

CREATE INDEX IF NOT EXISTS idx_articles_status ON articles (status);
CREATE INDEX IF NOT EXISTS idx_articles_topic ON articles (topic_id);
CREATE INDEX IF NOT EXISTS idx_articles_slug ON articles (slug);
CREATE INDEX IF NOT EXISTS idx_topics_last_seen ON topics (last_seen);
CREATE INDEX IF NOT EXISTS idx_obs_topic_day ON topic_observations (topic_id, day);
CREATE UNIQUE INDEX IF NOT EXISTS idx_articles_slug_unique ON articles (slug);
"""

#: Columns added after the first release, with the idempotent ALTER statement.
_ADDED_COLUMNS: dict[str, list[tuple[str, str]]] = {
    "run_log": [
        ("outcome", "TEXT NOT NULL DEFAULT ''"),
        ("reason", "TEXT NOT NULL DEFAULT ''"),
        ("stage", "TEXT NOT NULL DEFAULT ''"),
        ("details", "TEXT NOT NULL DEFAULT ''"),
    ],
    "topic_history": [
        ("topic_id", "INTEGER"),
    ],
}


def connect(db_path: Path | str) -> sqlite3.Connection:
    """Open a connection with sane pragmas and Row access."""
    path = Path(db_path)
    if path.parent and not path.parent.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    try:
        rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    except sqlite3.DatabaseError:
        return set()
    return {row[1] for row in rows}


def _ensure_columns(conn: sqlite3.Connection) -> list[str]:
    """Add any missing columns. Returns a list of ``table.column`` added."""
    added: list[str] = []
    for table, columns in _ADDED_COLUMNS.items():
        existing = _table_columns(conn, table)
        if not existing:
            continue  # table doesn't exist yet — CREATE above handles it
        for name, ddl in columns:
            if name not in existing:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")
                added.append(f"{table}.{name}")
    return added


def migrate(conn: sqlite3.Connection) -> list[str]:
    """Create/upgrade the schema. Idempotent. Returns the changes applied."""
    conn.executescript(_SCHEMA)
    added = _ensure_columns(conn)
    conn.execute(
        "INSERT INTO schema_meta (key, value) VALUES ('version', ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (str(SCHEMA_VERSION),),
    )
    conn.commit()
    if added:
        logger.info(kv("db_migrated", added=added))
    return added


def init_db(db_path: Path | str) -> sqlite3.Connection:
    """Convenience: open + migrate."""
    conn = connect(db_path)
    migrate(conn)
    return conn
