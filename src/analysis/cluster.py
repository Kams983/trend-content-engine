"""Group normalised items into clusters by embedding cosine similarity.

Uses a simple single-linkage / greedy threshold approach — no scipy
or sklearn clustering needed.  Returns list[list[dict]], one sub-list
per cluster.
"""

import logging

import numpy as np

from src.analysis.embed import embed

logger = logging.getLogger(__name__)

# Items with cosine similarity >= threshold are grouped together.
DEFAULT_THRESHOLD = 0.45


def _cosine_sim_matrix(vecs: np.ndarray) -> np.ndarray:
    """Pairwise cosine similarity matrix (n × n)."""
    norms = np.linalg.norm(vecs, axis=1, keepdims=True)
    norms = np.where(norms == 0, 1, norms)  # avoid /0
    normed = vecs / norms
    return normed @ normed.T


def _build_text(item: dict) -> str:
    """Combine title + content into a single string for embedding.

    Content is truncated to 300 chars to keep embedding fast on long
    abstracts while preserving enough signal for similarity grouping.
    """
    title = item.get('title', '')
    content = item.get('content', '')[:300]
    return f"{title} {content}".strip()


def cluster(items: list[dict], threshold: float = DEFAULT_THRESHOLD) -> list[list[dict]]:
    """Cluster *items* by cosine similarity of their embeddings.

    Algorithm:
        1. Embed all items.
        2. Build an n×n cosine-similarity matrix.
        3. Greedily merge items whose similarity >= *threshold* using
           Union-Find, so each connected component becomes one cluster.

    Items that are not similar to anything else become single-item clusters.
    """
    if not items:
        return []

    texts = [_build_text(it) for it in items]
    vecs = np.array(embed(texts), dtype=np.float32)
    sim = _cosine_sim_matrix(vecs)
    n = len(items)

    # ---------- Union-Find ----------
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
        for j in range(i + 1, n):
            if sim[i, j] >= threshold:
                union(i, j)

    # ---------- Group by root ----------
    groups: dict[int, list[dict]] = {}
    for idx in range(n):
        root = find(idx)
        groups.setdefault(root, []).append(items[idx])

    clusters = list(groups.values())
    logger.info(
        "Clustered %d items into %d clusters (threshold=%.2f)",
        n, len(clusters), threshold,
    )
    return clusters
