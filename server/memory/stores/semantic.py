from __future__ import annotations

import math
import os
from collections import Counter
from typing import Dict, List, Optional, Union


Vector = Union[Dict[str, float], List[float]]


class SemanticStore:
    """In-memory fallback semantic store with a Qdrant-like interface."""

    def __init__(self, url: str, collection: str, embedding_model: str):
        self.url = url
        self.collection = collection
        self.embedding_model = embedding_model
        self._items: Dict[str, Dict] = {}
        self._encoder = None
        self._qdrant = None
        self._backend = "memory"

        if os.getenv("MEMORY_DISABLE_ENCODER", "0") != "1":
            try:
                from sentence_transformers import SentenceTransformer

                self._encoder = SentenceTransformer(embedding_model)
            except Exception:
                self._encoder = None

        self._init_qdrant_backend()

    def _init_qdrant_backend(self) -> None:
        if self.url.startswith("memory://"):
            return

        try:
            from qdrant_client import QdrantClient
            from qdrant_client.http import models as qmodels

            client = QdrantClient(url=self.url, timeout=3.0)
            client.get_collections()

            vector_size = self._vector_size()
            existing = {c.name for c in client.get_collections().collections}
            if self.collection not in existing:
                client.create_collection(
                    collection_name=self.collection,
                    vectors_config=qmodels.VectorParams(size=vector_size, distance=qmodels.Distance.COSINE),
                )

            self._qdrant = client
            self._backend = "qdrant"
        except Exception:
            self._qdrant = None
            self._backend = "memory"

    def _vector_size(self) -> int:
        if self._encoder is not None:
            try:
                probe = self._encoder.encode("vector-size-probe", normalize_embeddings=True)
                return int(len(probe))
            except Exception:
                pass
        return 384

    @staticmethod
    def _embed_sparse(text: str) -> Dict[str, float]:
        tokens = [t.lower() for t in text.split() if t.strip()]
        counts = Counter(tokens)
        norm = math.sqrt(sum(v * v for v in counts.values())) or 1.0
        return {k: v / norm for k, v in counts.items()}

    def _embed(self, text: str) -> Vector:
        if self._encoder is not None:
            vec = self._encoder.encode(text, normalize_embeddings=True)
            return [float(v) for v in vec]
        return self._embed_sparse(text)

    @staticmethod
    def _cosine(a: Vector, b: Vector) -> float:
        if isinstance(a, dict) and isinstance(b, dict):
            if len(a) > len(b):
                a, b = b, a
            return sum(v * b.get(k, 0.0) for k, v in a.items())

        if isinstance(a, list) and isinstance(b, list):
            if not a or not b or len(a) != len(b):
                return 0.0
            dot = sum(x * y for x, y in zip(a, b))
            na = math.sqrt(sum(x * x for x in a)) or 1.0
            nb = math.sqrt(sum(y * y for y in b)) or 1.0
            return dot / (na * nb)

        return 0.0

    def upsert(self, chunk_id: str, text: str, metadata: Dict) -> str:
        if self._backend == "qdrant" and self._qdrant is not None and self._encoder is not None:
            from qdrant_client.http import models as qmodels

            payload = dict(metadata or {})
            payload["text"] = text
            point = qmodels.PointStruct(id=chunk_id, vector=self._embed(text), payload=payload)
            self._qdrant.upsert(collection_name=self.collection, points=[point], wait=True)
            return chunk_id

        self._items[chunk_id] = {
            "id": chunk_id,
            "text": text,
            "metadata": dict(metadata or {}),
            "vector": self._embed(text),
        }
        return chunk_id

    def search(self, query: str, filter: Optional[Dict] = None, top_k: int = 10) -> List[Dict]:
        if self._backend == "qdrant" and self._qdrant is not None and self._encoder is not None:
            from qdrant_client.http import models as qmodels

            query_filter = None
            if filter:
                must = [qmodels.FieldCondition(key=k, match=qmodels.MatchValue(value=v)) for k, v in filter.items()]
                query_filter = qmodels.Filter(must=must)

            hits = self._qdrant.search(
                collection_name=self.collection,
                query_vector=self._embed(query),
                query_filter=query_filter,
                limit=top_k,
            )
            out = []
            for hit in hits:
                payload = dict(hit.payload or {})
                text = payload.pop("text", "")
                out.append(
                    {
                        "id": str(hit.id),
                        "text": text,
                        "metadata": payload,
                        "score": float(hit.score),
                    }
                )
            return out

        qv = self._embed(query)
        matches: List[Dict] = []
        for item in self._items.values():
            md = item["metadata"]
            if filter and any(md.get(k) != v for k, v in filter.items()):
                continue
            score = self._cosine(qv, item["vector"])
            matches.append({"id": item["id"], "text": item["text"], "metadata": md, "score": score})
        matches.sort(key=lambda x: x["score"], reverse=True)
        return matches[:top_k]

    def delete(self, chunk_ids: List[str]) -> bool:
        if self._backend == "qdrant" and self._qdrant is not None:
            from qdrant_client.http import models as qmodels

            if not chunk_ids:
                return False
            self._qdrant.delete(
                collection_name=self.collection,
                points_selector=qmodels.PointIdsList(points=chunk_ids),
                wait=True,
            )
            return True

        deleted_any = False
        for chunk_id in chunk_ids:
            if chunk_id in self._items:
                del self._items[chunk_id]
                deleted_any = True
        return deleted_any

    def delete_by_memory_id(self, memory_id: str) -> int:
        if self._backend == "qdrant" and self._qdrant is not None:
            from qdrant_client.http import models as qmodels

            self._qdrant.delete(
                collection_name=self.collection,
                points_selector=qmodels.FilterSelector(
                    filter=qmodels.Filter(
                        must=[qmodels.FieldCondition(key="memory_id", match=qmodels.MatchValue(value=memory_id))]
                    )
                ),
                wait=True,
            )
            return 0

        to_delete = [cid for cid, item in self._items.items() if item["metadata"].get("memory_id") == memory_id]
        for cid in to_delete:
            del self._items[cid]
        return len(to_delete)
