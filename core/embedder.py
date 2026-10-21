"""
Turns text into 'meaning vectors' (embeddings).

Two sentences that mean the same thing get vectors pointing in nearly the same
direction, even if they use different words ("big cat" ~ "tiger"). We compare
directions with cosine similarity (1.0 = same meaning, ~0 = unrelated).

Backends, tried in order:
  1. fastembed            (ONNX runtime, light, no PyTorch)  <- preferred
  2. sentence-transformers (PyTorch)
If neither is installed / the model is not downloaded, returns None and the
system runs in keyword-only (BM25) mode - it still works, just less clever.
"""
import logging

import numpy as np

import config

log = logging.getLogger("van_mitra.embedder")


class Embedder:
    def __init__(self, backend, model, name):
        self.backend = backend
        self.model = model
        self.name = name

    def embed_docs(self, texts):
        return self._embed(list(texts))

    def embed_query(self, text):
        return self._embed([config.EMBED_QUERY_PREFIX + text])[0]

    def _embed(self, texts):
        if self.backend == "fastembed":
            vecs = np.array(list(self.model.embed(texts)), dtype=np.float32)
        else:
            vecs = np.asarray(self.model.encode(texts, normalize_embeddings=True), dtype=np.float32)
        norms = np.linalg.norm(vecs, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        return vecs / norms  # unit length -> dot product == cosine similarity


_cached = "unset"


def get_embedder(allow_download=False):
    """Load once and reuse. allow_download=True only during setup / index building."""
    global _cached
    if _cached != "unset":
        return _cached
    _cached = None
    cache_dir = str(config.MODELS_DIR / "embeddings")
    try:
        from fastembed import TextEmbedding
        kwargs = dict(cache_dir=cache_dir)
        if not allow_download:
            kwargs["local_files_only"] = True
        try:
            model = TextEmbedding(config.EMBED_MODEL, **kwargs)
        except TypeError:  # older fastembed without local_files_only
            kwargs.pop("local_files_only", None)
            model = TextEmbedding(config.EMBED_MODEL, **kwargs)
        _cached = Embedder("fastembed", model, config.EMBED_MODEL)
        log.info("Embeddings: fastembed / %s", config.EMBED_MODEL)
        return _cached
    except Exception as e:  # noqa: BLE001
        log.warning("fastembed unavailable (%s)", str(e).splitlines()[0][:160])
    try:
        from sentence_transformers import SentenceTransformer
        model = SentenceTransformer(config.EMBED_MODEL, cache_folder=cache_dir,
                                    local_files_only=not allow_download)
        _cached = Embedder("sentence-transformers", model, config.EMBED_MODEL)
        log.info("Embeddings: sentence-transformers / %s", config.EMBED_MODEL)
        return _cached
    except Exception as e:  # noqa: BLE001
        log.warning("sentence-transformers unavailable (%s)", str(e).splitlines()[0][:160])
    log.warning("No embedding model -> keyword-only (BM25) retrieval.")
    return None
