"""Text -> vector, for memory search.

EMBED_MODEL=hash        built-in hashing trick, no download. Matches exact words only.
                        Good for tests and the mock pipeline.
EMBED_MODEL=BAAI/bge-m3 real multilingual embeddings (Hindi / Hinglish aware).
                        Needs `pip install sentence-transformers`, runs on the Brev GPU.
"""
from __future__ import annotations

import hashlib
import re
import threading

import numpy as np

from config import SETTINGS

DIM_HASH = 512
_model = None
_lock = threading.Lock()


def _hash_embed(texts: list[str]) -> np.ndarray:
    out = np.zeros((len(texts), DIM_HASH), dtype=np.float32)
    for i, t in enumerate(texts):
        for tok in re.findall(r"\w+", t.lower()):
            h = int(hashlib.md5(tok.encode()).hexdigest(), 16)
            out[i, h % DIM_HASH] += 1.0 if (h >> 9) & 1 else -1.0
    norms = np.linalg.norm(out, axis=1, keepdims=True)
    return out / np.maximum(norms, 1e-9)


def embed(texts: list[str]) -> np.ndarray:
    """Return an (n, d) array of unit vectors."""
    if SETTINGS.embed_model == "hash":
        return _hash_embed(texts)
    global _model
    with _lock:
        if _model is None:
            from sentence_transformers import SentenceTransformer

            _model = SentenceTransformer(SETTINGS.embed_model)
        return np.asarray(_model.encode(texts, normalize_embeddings=True), dtype=np.float32)
