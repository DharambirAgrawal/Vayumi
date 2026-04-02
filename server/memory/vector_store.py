# =============================================================================
# server/memory/vector_store.py — ChromaDB Wrapper (User-Scoped Queries)
# =============================================================================
#
# PURPOSE:
#   Wraps ChromaDB for semantic vector search. ALL queries are scoped by
#   user_id — there is no code path that can retrieve another user's data.
#   Used for episodic memory storage and retrieval.
#
# STORAGE:
#   Phase 1: ChromaDB PersistentClient (local, file-based at server/data/vectordb/)
#   Production: Migrate to Qdrant hosted when:
#     - Any single user exceeds ~50,000 memory entries
#     - Total entries across all users exceed ~200,000
#
# COLLECTION: "episodic_memory"
#   Metadata per entry: hnsw:space = "cosine"
#   Each document has metadata: {user_id, speaker_id, timestamp, sensitivity, tags, ...}
#
# CLASS: VectorStore
#
#   __init__(self, persist_path: str | Path | None = None):
#     Default: server.paths.DEFAULT_VECTORDB_DIR
#     - Creates ChromaDB PersistentClient at persist_path
#     - Gets or creates "episodic_memory" collection with cosine similarity
#
#   async def store(self, doc_id: str, content: str, embedding: list[float],
#                   user_id: str, metadata: dict) -> None:
#     Stores a memory document with embedding.
#     metadata MUST include user_id (enforced here).
#     Calls: collection.add(documents=[content], embeddings=[embedding],
#            metadatas=[{user_id, **metadata}], ids=[doc_id])
#
#   async def query(self, embedding: list[float], user_id: str,
#                   top_k: int = 5, extra_filters: dict | None = None) -> list[dict]:
#     Retrieves relevant memories by semantic similarity.
#     ALWAYS filters by user_id (enforced — cannot query other users' data).
#     Builds where clause: {"user_id": user_id, **extra_filters}
#     Calls: collection.query(query_embeddings=[embedding], n_results=top_k,
#            where=where_clause)
#     Returns list of {id, content, metadata, distance} dicts.
#
#   async def query_deferred(self, embedding: list[float], user_id: str,
#                            top_k: int = 3) -> list[dict]:
#     Specialized query for deferred artifacts ("tell me later" pattern).
#     Filters: user_id + artifact_type="deferred_read"
#     Results ranked by: similarity first, then recency (created_at).
#
#   async def delete(self, doc_id: str, user_id: str) -> None:
#     Deletes a memory document. Verifies user_id ownership before deletion.
#
# IMPORTS NEEDED:
# =============================================================================

import chromadb
from pathlib import Path

from server.paths import DEFAULT_VECTORDB_DIR


class VectorStore:
    def __init__(self, persist_path: str | Path | None = None):
        path = Path(persist_path) if persist_path is not None else DEFAULT_VECTORDB_DIR
        path.mkdir(parents=True, exist_ok=True)
        self.client = chromadb.PersistentClient(path=str(path))
        self.collection = self.client.get_or_create_collection(
            name="episodic_memory",
            metadata={"hnsw:space": "cosine"},
        )

    async def store(self, doc_id: str, content: str, embedding: list[float],
                    user_id: str, metadata: dict) -> None:
        pass

    async def query(self, embedding: list[float], user_id: str,
                    top_k: int = 5, extra_filters: dict | None = None) -> list[dict]:
        pass

    async def query_deferred(self, embedding: list[float], user_id: str,
                             top_k: int = 3) -> list[dict]:
        pass

    async def delete(self, doc_id: str, user_id: str) -> None:
        pass
