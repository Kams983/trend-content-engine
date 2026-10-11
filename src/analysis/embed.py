"""Embed text using sentence-transformers/all-MiniLM-L6-v2 (CPU only).

The model is loaded once at import time so repeated calls are fast.
"""

import logging

import numpy as np
from sentence_transformers import SentenceTransformer

logger = logging.getLogger(__name__)

MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
logger.info("Loading embedding model %s …", MODEL_NAME)
_model = SentenceTransformer(MODEL_NAME, device="cpu")
logger.info("Model loaded (%d-dimensional embeddings).", _model.get_embedding_dimension())


def embed(texts: list[str], batch_size: int = 64) -> list[list[float]]:
    """Return one embedding vector per input text.

    Empty strings are replaced with a zero vector of the correct dimension.
    """
    if not texts:
        return []
    vecs = _model.encode(texts, batch_size=batch_size, show_progress_bar=False)
    return vecs.tolist()
