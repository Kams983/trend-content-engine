"""Precompute embeddings for the frozen fixtures.

Tests must not download a model or touch the network, so the canonical
``all-MiniLM-L6-v2`` vectors for the 120 fixture items are computed once and
committed as ``src/analysis/fixtures/fixture_embeddings.npz``.

Run (from the repo root):

    python scripts/precompute_fixture_embeddings.py

The script also prints cluster richness across thresholds, which is how
``CLUSTER_THRESHOLD`` was tuned on the fixtures.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import numpy as np  # noqa: E402

from src.analysis.cluster import build_embed_text, cluster, cluster_sources  # noqa: E402
from src.analysis.embed import embed_matrix  # noqa: E402
from src.ingest.fixtures_loader import DEFAULT_SOURCES, load_fixtures  # noqa: E402

OUT_PATH = REPO_ROOT / "src" / "analysis" / "fixtures" / "fixture_embeddings.npz"


def item_key(source: str, url: str) -> str:
    return f"{source}|{url}"


def main() -> int:
    fixtures = load_fixtures()
    keys: list[str] = []
    texts: list[str] = []
    items: list[dict] = []
    for source in DEFAULT_SOURCES:
        for item in fixtures[source]:
            keys.append(item_key(source, item["url"]))
            texts.append(build_embed_text(item))
            items.append(item)

    vectors = embed_matrix(texts)
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        OUT_PATH,
        keys=np.array(keys, dtype=str),
        texts=np.array(texts, dtype=str),
        vectors=vectors.astype(np.float32),
    )
    print(f"wrote {OUT_PATH}  shape={vectors.shape}")

    print("\ncluster richness by threshold:")
    for threshold in (0.30, 0.35, 0.40, 0.45, 0.50, 0.55, 0.60):
        groups = cluster(items, threshold=threshold)
        eligible = [g for g in groups if len(g) >= 3 and len(cluster_sources(g)) >= 2]
        best = max(groups, key=lambda g: (len(g), len(cluster_sources(g)))) if groups else []
        print(
            f"  t={threshold:.2f} clusters={len(groups):3d} eligible(3+/2src)={len(eligible):2d} "
            f"biggest={len(best)}/{len(cluster_sources(best))}src"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
