"""
Embedding seam (Phase 10). One job: turn passages into vectors, in this app's own container.

  ready()            -> bool      the model can be loaded (or the backend needs nothing)
  dimensions()       -> int       384 for the default model
  embed(texts)       -> list[list[float]]

Backends, chosen by EMBED (local | none):
  local  fastembed + BAAI/bge-small-en-v1.5 on CPU — no API key, no provider, nothing leaves the machine.
  none   raises; used by tests and by deployments that keep retrieval off (RETRIEVAL=off).
run.py never imports fastembed; it asks this module.
"""
import os
from typing import List

MODEL = os.environ.get("EMBED_MODEL", "BAAI/bge-small-en-v1.5")
DIMENSIONS = int(os.environ.get("EMBED_DIMENSIONS", "384"))
BACKEND = os.environ.get("EMBED", "local").strip().lower()
BATCH = int(os.environ.get("EMBED_BATCH", "64"))
_model = None  # loaded once per process; weights only, no state


class EmbedError(RuntimeError):
    """The embedder can't run here (model missing, backend off). Retrieval falls back to whole files."""


def dimensions() -> int:
    return DIMENSIONS


def _local():
    global _model
    if _model is None:
        try:
            from fastembed import TextEmbedding
        except ImportError as e:  # the image installs it; a bare checkout may not have it
            raise EmbedError("fastembed is not installed") from e
        _model = TextEmbedding(model_name=MODEL, cache_dir=os.environ.get("FASTEMBED_CACHE_PATH") or None)
    return _model


def ready() -> bool:
    if BACKEND != "local":
        return False
    try:
        _local()
        return True
    except Exception:
        return False


def embed(texts: List[str]) -> List[List[float]]:
    """Vectors for passages, in order. Empty input gives an empty list."""
    texts = [t if t.strip() else " " for t in texts]
    if not texts:
        return []
    if BACKEND != "local":
        raise EmbedError(f"EMBED={BACKEND!r}: no embedding backend")
    model = _local()
    out = [list(map(float, v)) for v in model.embed(texts, batch_size=BATCH)]
    if out and len(out[0]) != DIMENSIONS:
        raise EmbedError(f"{MODEL} returned {len(out[0])} dimensions, expected {DIMENSIONS}")
    return out
