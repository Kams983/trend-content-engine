"""Group normalised items into clusters by embedding cosine similarity.

Greedy centroid assignment: an item joins the existing cluster whose centroid
it is closest to, and only when that similarity clears ``threshold``; otherwise
it starts a new cluster. Comparing against the centroid instead of "any member"
is what stops A–B–C chain merges from gluing A to C, which is how unrelated
papers used to end up in one giant cluster. No scipy or sklearn needed.
Returns ``list[list[dict]]``, one sub-list per cluster.
"""

from __future__ import annotations

import logging

import numpy as np

from .embed import embed_matrix

logger = logging.getLogger(__name__)

#: Minimum cosine similarity between an item and a cluster centroid for the
#: item to join that cluster. 0.45 was tuned on the 120 frozen fixtures *and*
#: a live 119-item ingest (see scripts/precompute_fixture_embeddings.py):
#: unrelated arXiv abstracts already sit near 0.42 just from shared vocabulary,
#: so anything looser starts merging distinct stories.
DEFAULT_THRESHOLD = 0.45
#: How much of an item's content to include in the embedding text.
CONTENT_CHARS = 300


def build_embed_text(item: dict) -> str:
    """Title + truncated content — the canonical text used for embeddings.

    Shared by the pipeline and the fixture-embedding precompute script so the
    vectors always line up.
    """
    title = (item.get("title") or "").strip()
    content = (item.get("content") or "")[:CONTENT_CHARS]
    return f"{title} {content}".strip()


def cluster(items: list[dict], threshold: float = DEFAULT_THRESHOLD) -> list[list[dict]]:
    """Cluster *items* into groups of embedding-similar items.

    Single pass over the items in input order: O(n·k) comparisons against the
    ``k`` running centroids, so cost grows linearly with the number of clusters.
    Deterministic for a given input order and threshold.
    """
    if not items:
        return []

    vecs = embed_matrix([build_embed_text(it) for it in items])
    n = len(items)
    if n == 0:
        return []

    centroids = np.zeros((n, vecs.shape[1]), dtype=np.float32)
    members: list[list[int]] = []

    for idx in range(n):
        vec = vecs[idx]
        norm = float(np.linalg.norm(vec))
        unit = vec / norm if norm else vec

        if members:
            sims = centroids[: len(members)] @ unit
            best = int(np.argmax(sims))
            if float(sims[best]) >= threshold:
                members[best].append(idx)
                mean = vecs[members[best]].mean(axis=0)
                mean_norm = float(np.linalg.norm(mean))
                centroids[best] = mean / mean_norm if mean_norm else mean
                continue

        centroids[len(members)] = unit
        members.append([idx])

    clusters = [[items[i] for i in group] for group in members]
    clusters.sort(key=lambda c: (-len(c), c[0].get("title", "")))
    logger.info("event=clustered items=%d clusters=%d threshold=%s", n, len(clusters), threshold)
    return clusters


def cluster_label(cluster: list[dict]) -> str:
    """Display-only label: the first item's title, truncated."""
    if not cluster:
        return "empty"
    return (cluster[0].get("title") or "untitled")[:80]


def cluster_sources(cluster: list[dict]) -> list[str]:
    """Sorted unique source names in a cluster."""
    return sorted({it.get("source", "?") for it in cluster})


def centroid_of(items: list[dict]) -> np.ndarray:
    """L2-normalised mean embedding of *items* (the cluster centroid)."""
    if not items:
        return np.zeros(embed_matrix([""]).shape[1], dtype=np.float32)
    vecs = embed_matrix([build_embed_text(it) for it in items])
    mean = vecs.mean(axis=0)
    norm = float(np.linalg.norm(mean))
    if norm == 0.0:
        return mean.astype(np.float32)
    return (mean / norm).astype(np.float32)
