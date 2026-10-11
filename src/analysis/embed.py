"""Text embeddings (sentence-transformers/all-MiniLM-L6-v2, CPU only).

The model is loaded **lazily** so importing this module is cheap, and the
encoder is **injectable** so tests can supply deterministic vectors without
touching the network or the model weights.
"""

from __future__ import annotations

import logging
from typing import Callable, Sequence

import numpy as np

logger = logging.getLogger(__name__)

MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
EMBED_DIM = 384

_model = None
_encoder: Callable[[Sequence[str]], np.ndarray] | None = None


def get_model():
    """Load (once) and return the SentenceTransformer on CPU."""
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer

        logger.info("event=embedding_model_loading model=%s", MODEL_NAME)
        _model = SentenceTransformer(MODEL_NAME, device="cpu")
        logger.info("event=embedding_model_loaded dim=%d", _model.get_sentence_embedding_dimension())
    return _model


def set_encoder(encoder: Callable[[Sequence[str]], np.ndarray] | None) -> None:
    """Install a custom encoder (used by tests). ``None`` restores the model."""
    global _encoder
    _encoder = encoder


def reset_encoder() -> None:
    set_encoder(None)


def _normalize(matrix: np.ndarray) -> np.ndarray:
    """L2-normalise rows so cosine similarity is a plain dot product."""
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms = np.where(norms == 0, 1.0, norms)
    return (matrix / norms).astype(np.float32)


def embed_matrix(texts: Sequence[str], batch_size: int = 64) -> np.ndarray:
    """Return an ``(n, 384)`` float32, L2-normalised embedding matrix."""
    texts = list(texts)
    if not texts:
        return np.zeros((0, EMBED_DIM), dtype=np.float32)
    if _encoder is not None:
        raw = np.asarray(_encoder(texts), dtype=np.float32)
    else:
        raw = np.asarray(get_model().encode(texts, batch_size=batch_size, show_progress_bar=False), dtype=np.float32)
    if raw.ndim == 1:
        raw = raw.reshape(1, -1)
    return _normalize(raw)


def embed(texts: Sequence[str], batch_size: int = 64) -> list[list[float]]:
    """Return one embedding vector per input text (list-of-lists API)."""
    return embed_matrix(texts, batch_size=batch_size).tolist()


def cosine(a: np.ndarray, b: np.ndarray) -> float:
    """Cosine similarity of two 1-d vectors (assumed L2-normalised is fine too)."""
    denom = float(np.linalg.norm(a) * np.linalg.norm(b))
    if denom == 0.0:
        return 0.0
    return float(np.dot(a, b) / denom)
