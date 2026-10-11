"""Score and rank clusters by topic identity, velocity, novelty and richness.

Score
-----
``score = w_velocity*velocity + w_novelty*novelty
         + w_size*log1p(item_count) + w_sources*distinct_sources
         + w_engagement*mean_engagement_percentile``

* ``velocity`` — today's item count divided by the mean daily count over the
  last 7 days **for the same topic_id** (default 1.0 only when there is no
  history at all). The mean is taken over the days the topic was actually seen,
  which keeps intermittent sources from producing absurd spikes.
* ``novelty`` — 1 when the ``topic_id`` is new this run, else 0.
* ``engagement`` — per-source percentile rank, averaged over the cluster, so
  Hacker News points cannot swamp arXiv author counts.

Eligibility: at least ``MIN_CLUSTER_ITEMS`` items from at least
``MIN_CLUSTER_SOURCES`` distinct sources, and not inside the publish cooldown
(unless velocity clears the override).
"""

from __future__ import annotations

import logging
import math
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any

from ..config import Settings
from ..state import repo
from ..util.logging_setup import kv
from . import topics as topics_mod

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Engagement: per-source percentile ranks
# ---------------------------------------------------------------------------


def _item_key(item: dict) -> tuple[str, str]:
    return (item.get("source", "?"), item.get("url") or item.get("title", ""))


def engagement_percentiles(all_items: list[dict]) -> dict[tuple[str, str], float]:
    """Percentile rank (0..1) of each item's engagement within its own source."""
    by_source: dict[str, list[tuple[float, tuple[str, str]]]] = {}
    for item in all_items:
        by_source.setdefault(item.get("source", "?"), []).append(
            (float(item.get("engagement") or 0), _item_key(item))
        )

    ranks: dict[tuple[str, str], float] = {}
    for entries in by_source.values():
        entries.sort(key=lambda e: e[0])
        n = len(entries)
        # Average rank for ties so identical scores get identical percentiles.
        i = 0
        while i < n:
            j = i
            while j + 1 < n and entries[j + 1][0] == entries[i][0]:
                j += 1
            # Fraction of items strictly below, midpoint of the tie block.
            percentile = (i + j) / 2 / (n - 1) if n > 1 else 0.5
            for k in range(i, j + 1):
                ranks[entries[k][1]] = percentile
            i = j + 1
    return ranks


def _cluster_engagement(cluster: list[dict], percentiles: dict[tuple[str, str], float]) -> float:
    if not cluster:
        return 0.0
    return sum(percentiles.get(_item_key(it), 0.0) for it in cluster) / len(cluster)


# ---------------------------------------------------------------------------
# Velocity / novelty
# ---------------------------------------------------------------------------


def velocity_for(
    conn: sqlite3.Connection,
    topic_id: int,
    today_count: int,
    settings: Settings,
    now: datetime | None = None,
) -> tuple[float, int]:
    """Return ``(velocity, history_days)`` for a topic.

    ``history_days == 0`` means no prior history, in which case velocity is 1.0.
    """
    now = now or datetime.now(timezone.utc)
    since = (now - timedelta(days=7)).strftime("%Y-%m-%d")
    today = now.strftime("%Y-%m-%d")
    counts = repo.observation_counts(conn, topic_id, since, before_day=today)
    if not counts:
        return 1.0, 0
    avg = sum(counts) / len(counts)
    return float(today_count) / max(avg, 0.1), len(counts)


def in_cooldown(conn: sqlite3.Connection, topic_id: int, settings: Settings, now: datetime | None = None) -> bool:
    """True when the topic was published inside the cooldown window."""
    now = now or datetime.now(timezone.utc)
    last = repo.last_published_at(conn, topic_id)
    if not last:
        return False
    try:
        when = datetime.fromisoformat(last)
    except ValueError:
        return False
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return (now - when) < timedelta(days=settings.cooldown_days)


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------


def score_clusters(
    conn: sqlite3.Connection,
    clusters: list[list[dict]],
    all_items: list[dict],
    settings: Settings,
    now: datetime | None = None,
) -> list[dict]:
    """Score, rank and persist today's clusters. Returns the ranked list.

    Each entry::

        {"topic_id", "label", "sources" (list), "count", "velocity", "novelty",
         "size_term", "engagement", "score", "eligible", "ineligibility_reason",
         "is_new", "items"}
    """
    now = now or datetime.now(timezone.utc)
    if not clusters:
        return []

    percentiles = engagement_percentiles(all_items)
    assigned = topics_mod.assign_topics(conn, clusters, settings, now=now)
    weights = settings.score_weights()

    ranked: list[dict] = []
    for info in assigned:
        count = len(info["items"])
        source_count = info["source_count"]
        vel, history_days = velocity_for(conn, info["topic_id"], count, settings, now=now)
        novelty = 1.0 if info["is_new"] else 0.0
        size_term = math.log1p(count)
        engagement = _cluster_engagement(info["items"], percentiles)

        score = (
            weights["velocity"] * vel
            + weights["novelty"] * novelty
            + weights["size"] * size_term
            + weights["sources"] * source_count
            + weights["engagement"] * engagement
        )

        reason = ""
        if count < settings.min_cluster_items:
            reason = "too_few_items"
        elif source_count < settings.min_cluster_sources:
            reason = "too_few_sources"
        elif in_cooldown(conn, info["topic_id"], settings, now=now) and vel < settings.cooldown_velocity_override:
            reason = "cooldown"

        ranked.append(
            {
                "topic_id": info["topic_id"],
                "label": info["label"],
                "sources": info["sources"],
                "count": count,
                "velocity": round(vel, 3),
                "novelty": novelty,
                "size_term": round(size_term, 3),
                "engagement": round(engagement, 3),
                "history_days": history_days,
                "score": round(score, 4),
                "eligible": reason == "",
                "ineligibility_reason": reason,
                "is_new": info["is_new"],
                "items": info["items"],
            }
        )

    # Deterministic ordering: score, then richness, then topic_id.
    ranked.sort(key=lambda d: (-d["score"], -d["count"], -len(d["sources"]), d["topic_id"]))

    # Persist today's observations (after velocity was computed) and prune old topics.
    today = now.strftime("%Y-%m-%d")
    for entry in ranked:
        repo.record_observation(
            conn,
            topic_id=entry["topic_id"],
            day=today,
            item_count=entry["count"],
            source_count=len(entry["sources"]),
            sources=",".join(entry["sources"]),
            when=now.isoformat(),
        )
    topics_mod.prune(conn, settings, now=now)

    eligible = sum(1 for d in ranked if d["eligible"])
    top = ranked[0] if ranked else None
    logger.info(
        kv(
            "scored",
            clusters=len(ranked),
            eligible=eligible,
            top_label=(top["label"][:50] if top else ""),
            top_score=(top["score"] if top else 0),
            top_items=(top["count"] if top else 0),
            top_sources=(len(top["sources"]) if top else 0),
        )
    )
    return ranked


def eligible_clusters(ranked: list[dict], limit: int | None = None) -> list[dict[str, Any]]:
    """Return only the eligible entries, in ranked order."""
    out = [d for d in ranked if d.get("eligible")]
    return out[:limit] if limit else out
