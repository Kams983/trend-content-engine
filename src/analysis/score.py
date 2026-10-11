"""Score clusters by velocity and novelty against a trend history store.

The store is a SQLite database (``trend_store.sqlite``) with a single
table ``topic_history``:

    CREATE TABLE IF NOT EXISTS topic_history (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        topic       TEXT    NOT NULL,   -- cluster label (first item title)
        source      TEXT    NOT NULL,
        item_count  INTEGER NOT NULL,
        timestamp   TEXT    NOT NULL    -- ISO-8601
    );

Velocity:  today_count / avg_daily_count(last 7 days).
Novelty:   1.0 if topic never seen before, else 0.0.
Combined:  velocity + 2 * novelty (novelty gets double weight).
"""

import logging
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_DB = Path(__file__).resolve().parent.parent.parent / "trend_store.sqlite"
RETENTION_DAYS = 7


def _connect(db_path: Path | str) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        """CREATE TABLE IF NOT EXISTS topic_history (
               id         INTEGER PRIMARY KEY AUTOINCREMENT,
               topic      TEXT    NOT NULL,
               source     TEXT    NOT NULL,
               item_count INTEGER NOT NULL,
               timestamp  TEXT    NOT NULL
           )"""
    )
    conn.commit()
    return conn


def _cluster_label(cluster: list[dict]) -> str:
    """Return a short label for a cluster (first item's title, truncated)."""
    if not cluster:
        return "empty"
    return cluster[0].get("title", "untitled")[:80]


def _cluster_sources(cluster: list[dict]) -> str:
    """Comma-separated unique sources in the cluster."""
    return ",".join(sorted({it.get("source", "?") for it in cluster}))


def _velocity_score(conn: sqlite3.Connection, topic: str, today_count: int) -> float:
    """today_count / avg_daily_count over the last 7 days. Returns 1.0 if no history."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=RETENTION_DAYS)).isoformat()
    row = conn.execute(
        "SELECT SUM(item_count), COUNT(*) FROM topic_history "
        "WHERE topic = ? AND timestamp >= ?",
        (topic, cutoff),
    ).fetchone()
    total_7d, days_seen = row[0] or 0, row[1] or 0
    if days_seen == 0:
        return 1.0  # brand-new topic, treat as high velocity
    avg = total_7d / days_seen
    return today_count / max(avg, 0.1)


def _novelty_score(conn: sqlite3.Connection, topic: str) -> float:
    """1.0 if the topic has never appeared before, else 0.0."""
    row = conn.execute(
        "SELECT COUNT(*) FROM topic_history WHERE topic = ?",
        (topic,),
    ).fetchone()
    return 0.0 if (row[0] or 0) else 1.0


def _store_today(
    conn: sqlite3.Connection,
    topic: str,
    source: str,
    item_count: int,
    today: str,
) -> None:
    conn.execute(
        "INSERT INTO topic_history (topic, source, item_count, timestamp) "
        "VALUES (?, ?, ?, ?)",
        (topic, source, item_count, today),
    )


def score(
    clusters: list[list[dict]],
    top_n: int = 10,
    db_path: Path | str | None = None,
) -> list[dict]:
    """Score and rank clusters, then store today's data for future runs.

    Returns a list of dicts sorted by combined score (descending), each:
        {
            "label":       str,
            "sources":     str,
            "count":       int,
            "velocity":    float,
            "novelty":     float,
            "score":       float,
            "items":       list[dict],
        }
    """
    db = Path(db_path) if db_path else DEFAULT_DB
    conn = _connect(db)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")

    ranked: list[dict] = []
    for cluster in clusters:
        label = _cluster_label(cluster)
        sources = _cluster_sources(cluster)
        count = len(cluster)

        vel = _velocity_score(conn, label, count)
        nov = _novelty_score(conn, label)
        combined = vel + 2.0 * nov

        _store_today(conn, label, sources, count, today)

        ranked.append({
            "label": label,
            "sources": sources,
            "count": count,
            "velocity": round(vel, 3),
            "novelty": round(nov, 3),
            "score": round(combined, 3),
            "items": cluster,
        })

    conn.commit()
    conn.close()

    ranked.sort(key=lambda d: d["score"], reverse=True)
    return ranked[:top_n]
