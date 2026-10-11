"""Repository functions over the SQLite schema.

Small, explicit functions — no ORM. Every function takes an open connection so
callers control transactions and tests can use an in-memory database.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timezone
from typing import Any, Iterable, Sequence

from ..outcomes import as_outcome

logger = logging.getLogger(__name__)

# Article lifecycle
STATUS_PENDING = "pending_approval"
STATUS_APPROVED = "approved"
STATUS_REJECTED = "rejected"
STATUS_PUBLISHED = "published"
STATUS_FAILED = "failed"

# Publication lifecycle
PUB_OK = "ok"
PUB_FAILED = "failed"
PUB_SKIPPED = "skipped"


# ---------------------------------------------------------------------------
# Time helpers (UTC everywhere)
# ---------------------------------------------------------------------------


def now_iso() -> str:
    """Current UTC time as ISO-8601 with ``+00:00``."""
    return datetime.now(timezone.utc).isoformat()


def today_utc() -> str:
    """Current UTC date as ``YYYY-MM-DD``."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


# ---------------------------------------------------------------------------
# run_log
# ---------------------------------------------------------------------------


def record_run(
    conn: sqlite3.Connection,
    *,
    outcome: str,
    reason: str = "",
    stage: str = "",
    trend: str = "",
    source: str = "",
    item_count: int = 0,
    site_ok: bool = False,
    bluesky_ok: bool = False,
    telegram_ok: bool = False,
    details: str = "",
    timestamp: str | None = None,
) -> int:
    """Insert a run record and return its id."""
    cur = conn.execute(
        """
        INSERT INTO run_log
            (timestamp, trend, source, item_count, site_ok, bluesky_ok, telegram_ok,
             outcome, reason, stage, details)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            timestamp or now_iso(),
            trend,
            source,
            int(item_count),
            int(bool(site_ok)),
            int(bool(bluesky_ok)),
            int(bool(telegram_ok)),
            as_outcome(outcome),
            reason,
            stage,
            details,
        ),
    )
    conn.commit()
    return int(cur.lastrowid or 0)


def last_runs(conn: sqlite3.Connection, limit: int = 20) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM run_log ORDER BY id DESC LIMIT ?", (int(limit),)
    ).fetchall()


def runs_since(conn: sqlite3.Connection, since_iso: str) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM run_log WHERE timestamp >= ? ORDER BY id ASC", (since_iso,)
    ).fetchall()


# ---------------------------------------------------------------------------
# articles
# ---------------------------------------------------------------------------


def slug_exists(conn: sqlite3.Connection, slug: str) -> bool:
    row = conn.execute("SELECT 1 FROM articles WHERE slug = ? LIMIT 1", (slug,)).fetchone()
    return row is not None


def existing_titles(conn: sqlite3.Connection) -> set[str]:
    """Lower-cased titles already used, for duplicate detection."""
    rows = conn.execute("SELECT title FROM articles").fetchall()
    return {str(r[0]).strip().lower() for r in rows if r[0]}


def insert_article(
    conn: sqlite3.Connection,
    *,
    slug: str,
    title: str,
    teaser: str,
    body: str,
    topic_id: int | None,
    cluster_label: str,
    sources: Sequence[dict[str, Any]],
    tags: Sequence[str],
    status: str = STATUS_PENDING,
    run_id: str = "",
    created_at: str | None = None,
) -> int:
    cur = conn.execute(
        """
        INSERT INTO articles
            (run_id, slug, title, teaser, body, topic_id, cluster_label,
             sources_json, tags_json, status, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            run_id,
            slug,
            title,
            teaser,
            body,
            topic_id,
            cluster_label,
            json.dumps(list(sources), ensure_ascii=False),
            json.dumps(list(tags), ensure_ascii=False),
            status,
            created_at or now_iso(),
        ),
    )
    conn.commit()
    return int(cur.lastrowid or 0)


def get_article(conn: sqlite3.Connection, article_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM articles WHERE id = ?", (int(article_id),)).fetchone()


def get_article_by_slug(conn: sqlite3.Connection, slug: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM articles WHERE slug = ?", (slug,)).fetchone()


def articles_by_status(conn: sqlite3.Connection, status: str) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM articles WHERE status = ? ORDER BY id ASC", (status,)
    ).fetchall()


def set_article_status(conn: sqlite3.Connection, article_id: int, status: str) -> None:
    conn.execute("UPDATE articles SET status = ? WHERE id = ?", (status, int(article_id)))
    conn.commit()


def mark_published(conn: sqlite3.Connection, article_id: int, when: str | None = None) -> None:
    conn.execute(
        "UPDATE articles SET status = ?, published_at = ? WHERE id = ?",
        (STATUS_PUBLISHED, when or now_iso(), int(article_id)),
    )
    conn.commit()


def article_sources(conn: sqlite3.Connection, article: sqlite3.Row) -> list[dict[str, Any]]:
    """Decode ``sources_json`` from an article row."""
    try:
        return json.loads(article["sources_json"] or "[]")
    except (json.JSONDecodeError, TypeError):
        return []


def article_tags(conn: sqlite3.Connection, article: sqlite3.Row) -> list[str]:
    try:
        return json.loads(article["tags_json"] or "[]")
    except (json.JSONDecodeError, TypeError):
        return []


def articles_created_since(conn: sqlite3.Connection, since_iso: str) -> list[sqlite3.Row]:
    """Articles created at/after *since_iso* (used for the same-day guard)."""
    return conn.execute(
        "SELECT * FROM articles WHERE created_at >= ? ORDER BY id ASC", (since_iso,)
    ).fetchall()


def last_published_at(conn: sqlite3.Connection, topic_id: int) -> str | None:
    """Most recent publish time for a topic (for the duplicate-title/cooldown guard)."""
    row = conn.execute(
        "SELECT MAX(published_at) FROM articles WHERE topic_id = ? AND status = ?",
        (int(topic_id), STATUS_PUBLISHED),
    ).fetchone()
    return row[0] if row and row[0] else None


# ---------------------------------------------------------------------------
# publications (idempotency guard)
# ---------------------------------------------------------------------------


def get_publication(
    conn: sqlite3.Connection, article_id: int, target: str
) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM publications WHERE article_id = ? AND target = ?",
        (int(article_id), target),
    ).fetchone()


def record_publication(
    conn: sqlite3.Connection,
    *,
    article_id: int,
    target: str,
    status: str,
    external_id: str = "",
    url: str = "",
    error: str = "",
    created_at: str | None = None,
) -> bool:
    """Insert a publication record.

    Returns ``False`` when a record for ``(article_id, target)`` already exists —
    this is the idempotency guard that makes same-day reruns no-ops.
    """
    try:
        conn.execute(
            """
            INSERT INTO publications
                (article_id, target, status, external_id, url, error, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                int(article_id),
                target,
                status,
                external_id,
                url,
                error,
                created_at or now_iso(),
            ),
        )
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        conn.rollback()
        return False


def publications_for(conn: sqlite3.Connection, article_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM publications WHERE article_id = ? ORDER BY id ASC",
        (int(article_id),),
    ).fetchall()


# ---------------------------------------------------------------------------
# topics (centroid identity)
# ---------------------------------------------------------------------------


def insert_topic(
    conn: sqlite3.Connection,
    *,
    centroid: bytes,
    dim: int,
    label: str,
    when: str | None = None,
) -> int:
    stamp = when or now_iso()
    cur = conn.execute(
        "INSERT INTO topics (centroid, dim, label, first_seen, last_seen) VALUES (?, ?, ?, ?, ?)",
        (centroid, int(dim), label, stamp, stamp),
    )
    conn.commit()
    return int(cur.lastrowid or 0)


def update_topic(
    conn: sqlite3.Connection,
    topic_id: int,
    *,
    centroid: bytes | None = None,
    dim: int | None = None,
    label: str | None = None,
    when: str | None = None,
) -> None:
    sets: list[str] = ["last_seen = ?"]
    params: list[Any] = [when or now_iso()]
    if centroid is not None:
        sets.append("centroid = ?")
        params.append(centroid)
    if dim is not None:
        sets.append("dim = ?")
        params.append(int(dim))
    if label:
        sets.append("label = ?")
        params.append(label)
    params.append(int(topic_id))
    conn.execute(f"UPDATE topics SET {', '.join(sets)} WHERE topic_id = ?", params)
    conn.commit()


def topics_since(conn: sqlite3.Connection, since_iso: str) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM topics WHERE last_seen >= ? ORDER BY last_seen DESC", (since_iso,)
    ).fetchall()


def get_topic(conn: sqlite3.Connection, topic_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM topics WHERE topic_id = ?", (int(topic_id),)).fetchone()


def record_observation(
    conn: sqlite3.Connection,
    *,
    topic_id: int,
    day: str,
    item_count: int,
    source_count: int,
    sources: str,
    when: str | None = None,
) -> None:
    """Upsert today's observation for a topic (rerun-safe)."""
    conn.execute(
        """
        INSERT INTO topic_observations (topic_id, day, item_count, source_count, sources, timestamp)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(topic_id, day) DO UPDATE SET
            item_count = excluded.item_count,
            source_count = excluded.source_count,
            sources = excluded.sources,
            timestamp = excluded.timestamp
        """,
        (int(topic_id), day, int(item_count), int(source_count), sources, when or now_iso()),
    )
    conn.commit()


def observation_counts(
    conn: sqlite3.Connection, topic_id: int, since_day: str, before_day: str | None = None
) -> list[int]:
    """Per-day item counts for a topic in ``[since_day, before_day)``."""
    sql = "SELECT item_count FROM topic_observations WHERE topic_id = ? AND day >= ?"
    params: list[Any] = [int(topic_id), since_day]
    if before_day is not None:
        sql += " AND day < ?"
        params.append(before_day)
    sql += " ORDER BY day ASC"
    return [int(r[0]) for r in conn.execute(sql, params).fetchall()]


def prune_topics(conn: sqlite3.Connection, before_iso: str) -> int:
    """Delete topics (and their observations) not seen since *before_iso*."""
    ids = [
        r[0]
        for r in conn.execute("SELECT topic_id FROM topics WHERE last_seen < ?", (before_iso,)).fetchall()
    ]
    if not ids:
        return 0
    placeholders = ",".join("?" for _ in ids)
    conn.execute(f"DELETE FROM topic_observations WHERE topic_id IN ({placeholders})", ids)
    conn.execute(f"DELETE FROM topics WHERE topic_id IN ({placeholders})", ids)
    conn.commit()
    return len(ids)


def legacy_topic_history_count(conn: sqlite3.Connection) -> int:
    """Number of rows preserved in the legacy label-keyed table."""
    try:
        row = conn.execute("SELECT COUNT(*) FROM topic_history").fetchone()
    except sqlite3.DatabaseError:
        return 0
    return int(row[0]) if row else 0


def backfill_legacy_topic_ids(conn: sqlite3.Connection, mapping: dict[str, int]) -> int:
    """Attach a ``topic_id`` to legacy ``topic_history`` rows by exact label.

    Only used by the migration helper; rows that cannot be matched are left
    untouched (their ``topic_id`` stays NULL) so nothing is lost.
    """
    updated = 0
    for label, topic_id in mapping.items():
        cur = conn.execute(
            "UPDATE topic_history SET topic_id = ? WHERE topic = ? AND topic_id IS NULL",
            (int(topic_id), label),
        )
        updated += cur.rowcount or 0
    conn.commit()
    return updated


__all__: Iterable[str] = ()
