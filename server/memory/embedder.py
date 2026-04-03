# =============================================================================
# server/memory/embedder.py — HuggingFace Text Embeddings
# =============================================================================
#
# PURPOSE:
#   Generates text embeddings for semantic memory search using a local
#   sentence-transformers model. Runs entirely locally (no API calls).
#   Used by MemoryAgent for storing and retrieving memories, and by
#   ContextBuilder for querying relevant context.
#
# MODEL: all-MiniLM-L6-v2
#   - Provider: HuggingFace sentence-transformers (local, free)
#   - Dimensions: 384
#   - Speed: Fast (designed for real-time use)
#   - Quality: Good for semantic similarity tasks
#   - Size: ~80MB (auto-downloaded on first run by sentence-transformers)
#
# WHEN TO EMBED (always async, never blocks response):
#   - After memory is written (background task)
#   - When building context (to query vector store)
#   - When enrolling a new contact's description
#
# CLASS: Embedder
#
#   __init__(self, model_name: str = "all-MiniLM-L6-v2"):
#     - Loads SentenceTransformer model
#     - self.model = SentenceTransformer(model_name)
#
#   def embed(self, text: str) -> list[float]:
#     Generates an embedding for a single text string.
#     BLOCKING — call via asyncio.to_thread for async usage.
#     Returns: 384-dimensional vector as list of floats.
#     Uses: self.model.encode(text).tolist()
#
#   def embed_batch(self, texts: list[str]) -> list[list[float]]:
#     Generates embeddings for multiple texts at once (more efficient).
#     BLOCKING — call via asyncio.to_thread for async usage.
#     Returns: list of 384-dimensional vectors.
#     Uses: self.model.encode(texts).tolist()
#
# EMBEDDING MODEL VERSIONING:
#   If the embedding model is changed in the future, all stored embeddings
#   become incompatible. The embedding_model_version field in the users and
#   contacts tables tracks which model generated each voice embedding,
#   enabling future migration.
#
# IMPORTS NEEDED:
# =============================================================================

import logging

from sentence_transformers import SentenceTransformer

logger = logging.getLogger(__name__)


class Embedder:
    """
    Local text embedding engine using sentence-transformers.

    Wraps a SentenceTransformer model (default: all-MiniLM-L6-v2, 384-d)
    and exposes synchronous ``embed`` / ``embed_batch`` methods.

    Both methods are **blocking** (they run model inference on the CPU/GPU).
    In an async context, call them via ``asyncio.to_thread``::

        vector = await asyncio.to_thread(embedder.embed, "some text")
    """

    # Expected dimensionality for the default model.  Useful for callers
    # that need to pre-allocate or validate vectors.
    DEFAULT_MODEL_NAME = "all-MiniLM-L6-v2"
    DEFAULT_DIMENSIONS = 384

    def __init__(self, model_name: str = DEFAULT_MODEL_NAME):
        logger.info("Loading sentence-transformers model: %s", model_name)
        self.model = SentenceTransformer(model_name)
        self.model_name = model_name
        # Materialise the true dimension from the loaded model so downstream
        # code can query it without hard-coding.
        self.dimensions: int = self.model.get_sentence_embedding_dimension()
        logger.info(
            "Embedder ready — model=%s  dimensions=%d",
            self.model_name,
            self.dimensions,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def embed(self, text: str) -> list[float]:
        """
        Generate an embedding for a single text string.

        **Blocking** — in async code use ``asyncio.to_thread(embedder.embed, text)``.

        Parameters
        ----------
        text : str
            The input text to embed.  Empty / whitespace-only strings are
            accepted (the model will still return a vector, though it will
            carry little semantic information).

        Returns
        -------
        list[float]
            A 384-dimensional vector (for the default model) representing
            the semantic content of *text*.
        """
        if not text or not text.strip():
            logger.warning("embed() called with empty/blank text")

        # SentenceTransformer.encode accepts a single string and returns a
        # 1-D numpy array of shape (dimensions,).
        vector = self.model.encode(text)
        return vector.tolist()

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """
        Generate embeddings for multiple texts in one efficient call.

        Batching is significantly faster than calling :meth:`embed` in a
        loop because the model can parallelise internally.

        **Blocking** — in async code use
        ``asyncio.to_thread(embedder.embed_batch, texts)``.

        Parameters
        ----------
        texts : list[str]
            A list of input strings.  May be empty, in which case an
            empty list is returned.

        Returns
        -------
        list[list[float]]
            One 384-dimensional vector per input string, in the same order.
        """
        if not texts:
            return []

        # SentenceTransformer.encode with a list returns a 2-D numpy array
        # of shape (len(texts), dimensions).
        vectors = self.model.encode(texts)
        return vectors.tolist()