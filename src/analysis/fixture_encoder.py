"""Deterministic encoder backed by precomputed fixture embeddings.

Used by ``--use-fixtures`` runs and by the test suite so no model download or
network access is needed. Unknown texts get a stable, seeded pseudo-vector
derived from a hash of the text, which keeps runs reproducible.
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import Sequence

import numpy as np

from .embed import EMBED_DIM, set_encoder

logger = logging.getLogger(__name__)

DEFAULT_PATH = Path(__file__).resolve().parent / "fixtures" / "fixture_embeddings.npz"


def _seeded_vector(text: str) -> np.ndarray:
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    seed = int.from_bytes(digest[:8], "big") % (2**32)
    rng = np.random.default_rng(seed)
    vec = rng.standard_normal(EMBED_DIM).astype(np.float32)
    norm = float(np.linalg.norm(vec))
    return vec / norm if norm else vec


def load_encoder_map(path: Path | None = None) -> dict[str, np.ndarray]:
    """Load the ``{text: vector}`` map from the committed .npz."""
    target = path or DEFAULT_PATH
    if not target.exists():
        logger.warning("event=fixture_embeddings_missing path=%s", target)
        return {}
    data = np.load(target)
    texts = [str(t) for t in data["texts"]]
    vectors = data["vectors"].astype(np.float32)
    return {text: vectors[i] for i, text in enumerate(texts)}


def install_fixture_encoder(path: Path | None = None) -> int:
    """Install the fixture encoder globally. Returns the number of known texts."""
    mapping = load_encoder_map(path)

    def encoder(texts: Sequence[str]) -> np.ndarray:
        rows = [mapping.get(text, _seeded_vector(text)) for text in texts]
        return np.vstack(rows).astype(np.float32) if rows else np.zeros((0, EMBED_DIM), dtype=np.float32)

    set_encoder(encoder)
    logger.info("event=fixture_encoder_installed texts=%d", len(mapping))
    return len(mapping)
