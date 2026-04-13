from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Dict, List, Optional

from memory.models import MemoryType, SearchResponse, SearchResult
from memory.stores.blobs import BlobStore
from memory.stores.explicit import ExplicitStore
from memory.stores.graph import GraphStore
from memory.stores.semantic import SemanticStore


class RetrievalEngine:
    """Multi-strategy retrieval over semantic, graph, and explicit stores."""

    def __init__(
        self,
        semantic_store: SemanticStore,
        graph_store: GraphStore,
        explicit_store: ExplicitStore,
        blob_store: BlobStore,
    ):
        self.semantic_store = semantic_store
        self.graph_store = graph_store
        self.explicit_store = explicit_store
        self.blob_store = blob_store
        self._max_context_chars = 8000
        self._max_item_chars = 600

    def search(
        self,
        query: str,
        speaker_id: Optional[str] = None,
        type_filter: Optional[MemoryType] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        source_url: Optional[str] = None,
        top_k: int = 5,
    ) -> SearchResponse:
        with ThreadPoolExecutor(max_workers=3) as pool:
            fut_sem = pool.submit(self.semantic_search, query, speaker_id, max(top_k * 2, 10))
            fut_graph = pool.submit(self.graph_search, query, speaker_id, date_from, date_to)
            fut_meta = pool.submit(
                self.metadata_filter,
                type_filter,
                speaker_id,
                date_from,
                date_to,
                source_url,
                max(top_k * 3, 20),
            )
            merged = fut_sem.result() + fut_graph.result() + fut_meta.result()

        dedup: Dict[str, SearchResult] = {}
        for item in merged:
            prev = dedup.get(item.memory_id)
            if not prev or item.score > prev.score:
                dedup[item.memory_id] = item

        reranked = self.rerank(list(dedup.values()), query=query, top_k=top_k)
        return SearchResponse(context=self.build_context(reranked), results=reranked)

    def semantic_search(self, query: str, speaker_id: Optional[str] = None, top_k: int = 10) -> List[SearchResult]:
        filt = {"speaker_id": speaker_id} if speaker_id else None
        hits = self.semantic_store.search(query=query, filter=filt, top_k=top_k)
        out: List[SearchResult] = []
        for hit in hits:
            md = hit.get("metadata", {})
            out.append(
                SearchResult(
                    memory_id=str(md.get("memory_id", hit["id"])),
                    content=hit.get("text", ""),
                    score=float(hit.get("score", 0.0)),
                    type=MemoryType(md.get("type", "fact")),
                    source=md.get("source_url"),
                    speaker_id=str(md.get("speaker_id", "unknown")),
                    date=md.get("date"),
                    blob_path=md.get("blob_path"),
                )
            )
        return out

    def graph_search(
        self,
        query: str,
        speaker_id: Optional[str] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
    ) -> List[SearchResult]:
        hits = self.graph_store.search(query=query, speaker_id=speaker_id, date_from=date_from, date_to=date_to)
        out: List[SearchResult] = []
        for hit in hits:
            memory_id = hit.get("memory_id")
            if not memory_id:
                continue
            rec = self.explicit_store.get(memory_id)
            if not rec:
                continue
            out.append(
                SearchResult(
                    memory_id=rec.id,
                    content=rec.summary,
                    score=float(hit.get("score", 0.1)),
                    type=rec.type,
                    source=rec.source_url,
                    speaker_id=rec.speaker_id,
                    date=rec.created_at.date().isoformat(),
                    blob_path=rec.blob_path,
                )
            )
        return out

    def metadata_filter(
        self,
        type_filter: Optional[MemoryType] = None,
        speaker_id: Optional[str] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        source_url: Optional[str] = None,
        top_k: int = 20,
    ) -> List[SearchResult]:
        rows = self.explicit_store.filter(
            speaker_id=speaker_id,
            type_filter=type_filter,
            date_from=date_from,
            date_to=date_to,
            source_url=source_url,
            limit=top_k,
        )
        return [
            SearchResult(
                memory_id=r.id,
                content=r.summary,
                score=0.2,
                type=r.type,
                source=r.source_url,
                speaker_id=r.speaker_id,
                date=r.created_at.date().isoformat(),
                blob_path=r.blob_path,
            )
            for r in rows
        ]

    def rerank(self, results: List[SearchResult], query: str, top_k: int = 5) -> List[SearchResult]:
        _ = query
        now = datetime.utcnow()
        rescored: List[SearchResult] = []
        for r in results:
            recency = 0.0
            if r.date:
                try:
                    dt = datetime.fromisoformat(r.date)
                    age_days = max(0.0, (now - dt).days)
                    recency = 1.0 / (1.0 + age_days / 30.0)
                except ValueError:
                    recency = 0.0
            r.score = float(r.score) + 0.15 * recency
            rescored.append(r)
        rescored.sort(key=lambda x: x.score, reverse=True)
        return rescored[:top_k]

    def build_context(self, results: List[SearchResult]) -> str:
        if not results:
            return "[MEMORY CONTEXT]\nNo relevant memories found."
        lines: List[str] = ["[MEMORY CONTEXT]"]
        current_len = len(lines[0]) + 1
        for r in results:
            header = f"[{r.type.value.upper()} | {r.date or 'unknown-date'} | speaker: {r.speaker_id}]"
            if r.source:
                header = f"[{r.type.value.upper()} | {r.source} | speaker: {r.speaker_id} | {r.date or 'unknown-date'}]"

            content = (r.content or "").strip()
            if len(content) > self._max_item_chars:
                content = content[: self._max_item_chars - 3].rstrip() + "..."

            projected = current_len + len(header) + 1 + len(content) + 1
            if projected > self._max_context_chars:
                remaining = self._max_context_chars - current_len
                if remaining > 60:
                    footer = "[TRUNCATED] Additional relevant memories omitted due to context size limit."
                    lines.append(footer[: remaining - 1])
                break

            lines.append(header)
            lines.append(content)
            current_len = projected
        return "\n".join(lines)

    def load_multimodal_blocks(self, results: List[SearchResult]) -> List[Dict]:
        blocks: List[Dict] = []
        for r in results:
            if r.type not in {MemoryType.IMAGE, MemoryType.AUDIO}:
                continue
            if not r.blob_path or not self.blob_store.exists(r.blob_path):
                continue
            media_type = "image/png" if r.type == MemoryType.IMAGE else "audio/mp3"
            blocks.append(
                {
                    "type": "image" if r.type == MemoryType.IMAGE else "audio",
                    "source": {
                        "type": "base64",
                        "media_type": media_type,
                        "data": self.blob_store.load_as_base64(r.blob_path),
                    },
                }
            )
        return blocks
