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
# ISOLATION RULES:
#   Every query embeds user_id in the WHERE clause.  There is no code path
#   that can retrieve, update, or delete another user's vectors.
#
# IMPORTS NEEDED:
# =============================================================================

import asyncio
import logging
from pathlib import Path

import chromadb

from server.paths import DEFAULT_VECTORDB_DIR

logger = logging.getLogger(__name__)


class VectorStore:
    """
    User-scoped ChromaDB wrapper for episodic memory vectors.

    All public methods are ``async`` and offload the blocking ChromaDB
    calls to a thread via ``asyncio.to_thread`` so the event loop is
    never stalled.

    Every method that touches stored data requires a ``user_id`` and
    embeds it in the ChromaDB ``where`` filter, making cross-user data
    access structurally impossible.
    """

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def __init__(self, persist_path: str | Path | None = None):
        path = Path(persist_path) if persist_path is not None else DEFAULT_VECTORDB_DIR
        path.mkdir(parents=True, exist_ok=True)

        self.client = chromadb.PersistentClient(path=str(path))
        self.collection = self.client.get_or_create_collection(
            name="episodic_memory",
            metadata={"hnsw:space": "cosine"},
        )
        logger.info(
            "VectorStore ready — %s  (%d existing documents)",
            path,
            self.collection.count(),
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _build_where(user_id: str, extra_filters: dict | None = None) -> dict:
        """
        Build a ChromaDB ``where`` clause that always includes user_id.

        ChromaDB filter syntax:
          - Single condition:  ``{"user_id": "abc"}``
          - Multiple conditions: ``{"$and": [{...}, {...}]}``

        ``extra_filters`` keys are added as individual equality matchers
        combined with ``$and``.
        """
        conditions: list[dict] = [{"user_id": user_id}]

        if extra_filters:
            for key, value in extra_filters.items():
                conditions.append({key: value})

        if len(conditions) == 1:
            return conditions[0]

        return {"$and": conditions}

    @staticmethod
    def _unpack_query_result(result: dict) -> list[dict]:
        """
        Flatten ChromaDB's nested query result into a simple list of dicts.

        ChromaDB returns::

            {
                "ids":        [[id1, id2, ...]],
                "documents":  [[doc1, doc2, ...]],
                "metadatas":  [[meta1, meta2, ...]],
                "distances":  [[dist1, dist2, ...]],
            }

        We return::

            [
                {"id": id1, "content": doc1, "metadata": meta1, "distance": dist1},
                ...
            ]
        """
        ids = result.get("ids") or [[]]
        documents = result.get("documents") or [[]]
        metadatas = result.get("metadatas") or [[]]
        distances = result.get("distances") or [[]]

        # ChromaDB wraps everything in an outer list (one per query embedding).
        ids = ids[0] if ids else []
        documents = documents[0] if documents else []
        metadatas = metadatas[0] if metadatas else []
        distances = distances[0] if distances else []

        results: list[dict] = []
        for doc_id, content, metadata, distance in zip(
            ids, documents, metadatas, distances
        ):
            results.append(
                {
                    "id": doc_id,
                    "content": content,
                    "metadata": metadata or {},
                    "distance": distance,
                }
            )
        return results

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def store(
        self,
        doc_id: str,
        content: str,
        embedding: list[float],
        user_id: str,
        metadata: dict,
    ) -> None:
        """
        Store a memory document with its embedding vector.

        Parameters
        ----------
        doc_id : str
            Unique identifier for this memory entry.
        content : str
            The text content (stored as the ChromaDB document).
        embedding : list[float]
            Pre-computed embedding vector (384-d for all-MiniLM-L6-v2).
        user_id : str
            Owner of this memory.  Injected into metadata unconditionally
            so it can never be omitted or spoofed by the caller.
        metadata : dict
            Additional metadata (speaker_id, timestamp, sensitivity,
            tags, etc.).  ``user_id`` is overwritten here to guarantee
            scoping.
        """
        # Enforce user_id in metadata — caller cannot omit or override
        safe_metadata = {**metadata, "user_id": user_id}

        # ChromaDB metadata values must be str, int, float, or bool.
        # Serialise any list/dict values to JSON strings.
        import json

        for key, value in safe_metadata.items():
            if isinstance(value, (list, dict)):
                safe_metadata[key] = json.dumps(value)

        def _blocking_store():
            self.collection.add(
                ids=[doc_id],
                documents=[content],
                embeddings=[embedding],
                metadatas=[safe_metadata],
            )

        await asyncio.to_thread(_blocking_store)
        logger.debug("Stored vector %s for user %s", doc_id, user_id)

    async def query(
        self,
        embedding: list[float],
        user_id: str,
        top_k: int = 5,
        extra_filters: dict | None = None,
    ) -> list[dict]:
        """
        Retrieve the most semantically similar memories for a user.

        Parameters
        ----------
        embedding : list[float]
            Query vector to compare against stored embeddings.
        user_id : str
            Scoping filter — only this user's memories are searched.
        top_k : int
            Maximum number of results to return.
        extra_filters : dict | None
            Optional additional equality filters (e.g.
            ``{"sensitivity": "normal"}``).  Combined with user_id via
            ``$and``.

        Returns
        -------
        list[dict]
            Each dict contains ``id``, ``content``, ``metadata``, and
            ``distance`` (cosine distance — lower is more similar).
            Ordered by ascending distance (best match first).
        """
        where = self._build_where(user_id, extra_filters)

        def _blocking_query():
            return self.collection.query(
                query_embeddings=[embedding],
                n_results=top_k,
                where=where,
            )

        raw = await asyncio.to_thread(_blocking_query)
        results = self._unpack_query_result(raw)

        logger.debug(
            "Query for user %s returned %d results (top_k=%d)",
            user_id,
            len(results),
            top_k,
        )
        return results

    async def query_deferred(
        self,
        embedding: list[float],
        user_id: str,
        top_k: int = 3,
    ) -> list[dict]:
        """
        Specialised query for deferred artifacts ("tell me later" pattern).

        Filters to documents where ``artifact_type == "deferred_read"``
        and ranks by semantic similarity first, then by recency
        (``created_at`` descending) as a tie-breaker.

        Parameters
        ----------
        embedding : list[float]
            Query vector representing the user's current request.
        user_id : str
            Scoping filter.
        top_k : int
            Maximum results.

        Returns
        -------
        list[dict]
            Matching deferred artifacts sorted by relevance then recency.
        """
        results = await self.query(
            embedding=embedding,
            user_id=user_id,
            top_k=top_k,
            extra_filters={"artifact_type": "deferred_read"},
        )

        # Secondary sort: among results with similar distances, prefer
        # more recent entries.  ChromaDB returns by distance ascending;
        # we apply a stable re-sort that keeps distance as primary key
        # but breaks ties with recency (created_at descending).
        def _sort_key(item: dict):
            # Lower distance = better match (primary, ascending)
            distance = item.get("distance", 1.0)
            # More recent = higher priority (secondary, descending via negation)
            created_at = item.get("metadata", {}).get("created_at", "")
            return (distance, _invert_timestamp(created_at))

        results.sort(key=_sort_key)

        logger.debug(
            "Deferred query for user %s returned %d results",
            user_id,
            len(results),
        )
        return results

    async def delete(self, doc_id: str, user_id: str) -> None:
        """
        Delete a memory document after verifying user ownership.

        Parameters
        ----------
        doc_id : str
            The document to delete.
        user_id : str
            Must match the ``user_id`` in the document's metadata.
            If the document doesn't exist or belongs to a different user,
            the call is silently ignored (no error, no deletion).
        """

        def _blocking_delete():
            # Step 1: Verify the document belongs to this user
            existing = self.collection.get(
                ids=[doc_id],
                include=["metadatas"],
            )

            ids = existing.get("ids") or []
            metadatas = existing.get("metadatas") or []

            if not ids:
                logger.warning(
                    "Delete requested for non-existent doc %s (user %s)",
                    doc_id,
                    user_id,
                )
                return

            doc_metadata = metadatas[0] if metadatas else {}
            if doc_metadata.get("user_id") != user_id:
                logger.warning(
                    "Delete blocked — doc %s does not belong to user %s",
                    doc_id,
                    user_id,
                )
                return

            # Step 2: Safe to delete — ownership confirmed
            self.collection.delete(ids=[doc_id])

        await asyncio.to_thread(_blocking_delete)
        logger.debug("Deleted vector %s for user %s", doc_id, user_id)


# ==========================================================================
# Module-level helpers
# ==========================================================================

def _invert_timestamp(ts: str) -> str:
    """
    Return a string that sorts in the *opposite* order of *ts*.

    Used as a secondary sort key so that among equal-distance results,
    more recent timestamps (lexicographically larger ISO strings) sort
    first.  We achieve this by replacing each character with its
    complement within the printable ASCII range.

    Only needs to produce a *relative* ordering — the actual characters
    are irrelevant.
    """
    if not ts:
        # Empty timestamps sort last (least recent)
        return "\xff"
    return "".join(chr(126 - ord(c)) for c in ts)