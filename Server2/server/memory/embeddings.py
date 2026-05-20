from __future__ import annotations

from typing import TYPE_CHECKING

from server.logger import get_logger

if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer

log = get_logger("memory.embeddings")

_MODEL_NAME = "BAAI/bge-small-en-v1.5"
_EMBEDDING_DIM = 384
_model: SentenceTransformer | None = None


def embedding_dim() -> int:
    return _EMBEDDING_DIM


def init_embedder() -> None:
    global _model
    if _model is not None:
        return
    from sentence_transformers import SentenceTransformer

    log.info("embeddings.loading", model=_MODEL_NAME)
    _model = SentenceTransformer(_MODEL_NAME)
    log.info("embeddings.ready", dim=_EMBEDDING_DIM)


def embed_text(text: str) -> list[float]:
    if _model is None:
        raise RuntimeError("Embedder not initialized — call init_embedder first")
    vector = _model.encode(text, normalize_embeddings=True)
    return vector.tolist()


def close_embedder() -> None:
    global _model
    _model = None
    log.info("embeddings.closed")
