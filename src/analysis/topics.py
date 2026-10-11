"""Stable topic identity via embedding centroids.

The old scorer keyed everything on the cluster *label* (the first item's
title), which changes every day — so novelty was almost always 1.0 and velocity
almost always fell back to 1.0. Instead we:

* compute each cluster's 384-d centroid,
* match it against topic centroids seen in the last ``TOPIC_LOOKBACK_DAYS``
  days when cosine similarity >= ``TOPIC_SIMILARITY_THRESHOLD``,
* otherwise mint a new ``topic_id``.

The label stays display-only.
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timedelta, timezone

import numpy as np

from ..config import Settings
from ..state import repo
from ..util.logging_setup import kv
from .cluster import centroid_of, cluster_label, cluster_sources

logger = logging.getLogger(__name__)


def encode_centroid(vec: np.ndarray) -> bytes:
    """float32 centroid → bytes for a SQLite BLOB."""
    return np.asarray(vec, dtype=np.float32).tobytes()


def decode_centroid(blob: bytes, dim: int) -> np.ndarray:
    """bytes → float32 centroid (truncated to *dim*)."""
    return np.frombuffer(blob, dtype=np.float32)[:dim].astype(np.float32)


def _load_recent_topics(conn: sqlite3.Connection, cutoff_iso: str) -> list[sqlite3.Row]:
    return repo.topics_since(conn, cutoff_iso)


def assign_topics(
    conn: sqlite3.Connection,
    clusters: list[list[dict]],
    settings: Settings,
    now: datetime | None = None,
) -> list[dict]:
    """Assign a stable ``topic_id`` to every cluster.

    Returns one dict per cluster (same order) with:
        ``topic_id``, ``centroid`` (np.ndarray), ``label``, ``is_new``,
        ``sources`` (list), ``source_count``, ``items``.
    """
    if not clusters:
        return []

    now = now or datetime.now(timezone.utc)
    cutoff = (now - timedelta(days=settings.topic_lookback_days)).isoformat()
    recent = _load_recent_topics(conn, cutoff)

    # Pre-compute cluster centroids once and reuse (score computes a mean too).
    centroids = [centroid_of(cluster) for cluster in clusters]

    topic_ids = [int(row["topic_id"]) for row in recent]
    topic_centroids = (
        np.vstack([decode_centroid(row["centroid"], int(row["dim"])) for row in recent])
        if recent
        else np.zeros((0, centroids[0].shape[0]), dtype=np.float32)
    )

    claimed: set[int] = set()
    results: list[dict] = []

    for cluster, centroid in zip(clusters, centroids):
        label = cluster_label(cluster)
        sources = cluster_sources(cluster)
        match_id: int | None = None

        if topic_centroids.shape[0]:
            sims = topic_centroids @ centroid  # both L2-normalised → cosine
            order = np.argsort(-sims)[:5]
            for idx in order:
                candidate = topic_ids[int(idx)]
                if candidate in claimed:
                    continue
                if float(sims[int(idx)]) >= settings.topic_similarity_threshold:
                    match_id = candidate
                    break

        if match_id is not None:
            claimed.add(match_id)
            # Adaptive running centroid: 50% old + 50% new keeps identity stable
            # while still tracking a slowly drifting topic.
            old = decode_centroid(
                next(r["centroid"] for r in recent if int(r["topic_id"]) == match_id),
                len(centroid),
            )
            blended = old * 0.5 + centroid * 0.5
            norm = float(np.linalg.norm(blended))
            blended = (blended / norm).astype(np.float32) if norm else blended
            repo.update_topic(
                conn, match_id, centroid=encode_centroid(blended), dim=len(centroid), label=label, when=now.isoformat()
            )
            results.append(
                {
                    "topic_id": match_id,
                    "centroid": blended,
                    "label": label,
                    "is_new": False,
                    "sources": sources,
                    "source_count": len(sources),
                    "items": cluster,
                }
            )
        else:
            new_id = repo.insert_topic(
                conn, centroid=encode_centroid(centroid), dim=len(centroid), label=label, when=now.isoformat()
            )
            claimed.add(new_id)
            results.append(
                {
                    "topic_id": new_id,
                    "centroid": centroid,
                    "label": label,
                    "is_new": True,
                    "sources": sources,
                    "source_count": len(sources),
                    "items": cluster,
                }
            )

    logger.info(
        kv(
            "topics_assigned",
            clusters=len(clusters),
            new=sum(1 for r in results if r["is_new"]),
            matched=sum(1 for r in results if not r["is_new"]),
        )
    )
    return results


def prune(conn: sqlite3.Connection, settings: Settings, now: datetime | None = None) -> int:
    """Drop topics (and observations) not seen within the retention window."""
    now = now or datetime.now(timezone.utc)
    cutoff = (now - timedelta(days=settings.topic_retention_days)).isoformat()
    removed = repo.prune_topics(conn, cutoff)
    if removed:
        logger.info(kv("topics_pruned", removed=removed, retention_days=settings.topic_retention_days))
    return removed
