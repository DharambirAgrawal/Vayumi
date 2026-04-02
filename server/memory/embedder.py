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

from sentence_transformers import SentenceTransformer


class Embedder:
    def __init__(self, model_name: str = "all-MiniLM-L6-v2"):
        self.model = SentenceTransformer(model_name)
        self.model_name = model_name

    def embed(self, text: str) -> list[float]:
        pass

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        pass
