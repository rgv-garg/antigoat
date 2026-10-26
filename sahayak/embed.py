"""Text -> vector, for memory search.

EMBED_MODEL=hash        built-in hashing trick, no download. Matches exact words only.
                        Good for tests and the mock pipeline.
EMBED_MODEL=BAAI/bge-m3 real multilingual embeddings (Hindi / Hinglish aware).
                        Needs `pip install sentence-transformers`, runs on the Brev GPU.
EMBED_MODEL=nvidia:<model>  hosted NVIDIA embeddings over the API (no GPU, no download) -
                        e.g. nvidia:nvidia/llama-3.2-nv-embedqa-1b-v2. Uses LLM_BASE_URL /
                        LLM_API_KEY when they point at integrate.api.nvidia.com. For the
                        hosted demo (Hugging Face Space, CPU only).
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


_cache: dict[str, np.ndarray] = {}
_nv_state: str | None = None  # None (untried) | "ok" | "failed" (sticky hash fallback)


def _nvidia_embed(texts: list[str]) -> np.ndarray:
    """Hosted NVIDIA embedding NIM (OpenAI-compatible /embeddings). Cached per text."""
    import os

    from openai import OpenAI

    model = SETTINGS.embed_model.split(":", 1)[1]
    base = os.environ.get("EMBED_BASE_URL", "https://integrate.api.nvidia.com/v1")
    key = os.environ.get("EMBED_API_KEY") or SETTINGS.sahayak.api_key
    todo = [t for t in dict.fromkeys(texts) if t not in _cache]
    if todo:
        client = OpenAI(base_url=base, api_key=key, timeout=60)
        for i in range(0, len(todo), 32):
            batch = todo[i:i + 32]
            r = client.embeddings.create(model=model, input=[b[:2000] or " " for b in batch],
                                         extra_body={"input_type": "passage", "truncate": "END"})
            for t, d in zip(batch, r.data):
                v = np.asarray(d.embedding, dtype=np.float32)
                _cache[t] = v / max(float(np.linalg.norm(v)), 1e-9)
    return np.stack([_cache[t] for t in texts])


def embed(texts: list[str]) -> np.ndarray:
    """Return an (n, d) array of unit vectors."""
    if SETTINGS.embed_model == "hash":
        return _hash_embed(texts)
    if SETTINGS.embed_model.startswith("nvidia:"):
        global _nv_state
        if _nv_state == "failed":
            return _hash_embed(texts)
        import time
        for attempt in range(3):
            try:
                out = _nvidia_embed(texts)
                _nv_state = "ok"
                return out
            except Exception:  # noqa: BLE001
                if _nv_state is None:  # first call ever: fall back for good (dimensions stay consistent)
                    _nv_state = "failed"
                    return _hash_embed(texts)
                if attempt == 2:
                    raise
                time.sleep(1.5 * (attempt + 1))
    global _model
    with _lock:
        if _model is None:
            from sentence_transformers import SentenceTransformer

            try:  # half precision on GPU: ~half the memory (the LLM server shares this GPU)
                import torch
                kw = {"model_kwargs": {"torch_dtype": torch.float16}} if torch.cuda.is_available() else {}
            except Exception:  # noqa: BLE001
                kw = {}
            _model = SentenceTransformer(SETTINGS.embed_model, **kw)
        return np.asarray(_model.encode(texts, normalize_embeddings=True, batch_size=16), dtype=np.float32)
