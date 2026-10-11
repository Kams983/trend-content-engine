"""Group normalised items into clusters by embedding cosine similarity.

Simple greedy single-linkage via Union-Find — no scipy or sklearn needed.
Returns ``list[list[dict]]``, one sub-list per cluster.
"""

from __future__ import annotations

import logging

import numpy as np

from .embed import embed_matrix

logger = logging.getLogger(__name__)

#: Items with cosine similarity >= threshold are grouped together.
#: 0.40 was tuned on the 120 frozen fixtures (see
#: scripts/precompute_fixture_embeddings.py): low enough to form rich
#: cross-source clusters, high enough to keep them coherent.
DEFAULT_THRESHOLD = 0.40
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


def cosine_sim_matrix(vecs: np.ndarray) -> np.ndarray:
    """Pairwise cosine similarity matrix for L2-normalised (or raw) rows."""
    if vecs.size == 0:
        return np.zeros((0, 0), dtype=np.float32)
    norms = np.linalg.norm(vecs, axis=1, keepdims=True)
    norms = np.where(norms == 0, 1.0, norms)
    normed = vecs / norms
    return (normed @ normed.T).astype(np.float32)


def cluster(items: list[dict], threshold: float = DEFAULT_THRESHOLD) -> list[list[dict]]:
    """Cluster *items* into groups of embedding-similar items."""
    if not items:
        return []

    vecs = embed_matrix([build_embed_text(it) for it in items])
    sim = cosine_sim_matrix(vecs)
    n = len(items)

    parent = list(range(n))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for i in range(n):
        row = sim[i]
        for j in range(i + 1, n):
            if row[j] >= threshold:
                union(i, j)

    groups: dict[int, list[dict]] = {}
    for idx in range(n):
        groups.setdefault(find(idx), []).append(items[idx])

    clusters = sorted(groups.values(), key=lambda c: (-len(c), c[0].get("title", "")))
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
