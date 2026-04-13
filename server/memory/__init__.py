from __future__ import annotations

import base64
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from memory.config import MemoryConfig
from memory.constants import (
    DEFAULT_MEMORY_BLOB_DIR,
    DEFAULT_MEMORY_DB_PATH,
    resolve_repo_relative_path,
)
from memory.errors import MemoryIngestionError, MemoryStoreError, MemoryValidationError
from memory.ingestion.audio import AudioIngester
from memory.ingestion.file import FileIngester
from memory.ingestion.image import ImageIngester
from memory.ingestion.link import LinkIngester
from memory.ingestion.meeting import MeetingIngester
from memory.models import IngestResponse, MemoryRecord, MemoryType, SearchResponse, UserModel
from memory.personalization import PersonalizationLayer
from memory.retrieval import RetrievalEngine
from memory.router import MemoryRouter
from memory.short_term import ShortTermBuffer
from memory.stores.blobs import BlobStore
from memory.stores.explicit import ExplicitStore
from memory.stores.graph import GraphStore
from memory.stores.semantic import SemanticStore


class MemorySystem:
    """Main entry point for memory operations."""

    def __init__(
        self,
        speaker_id: str,
        qdrant_url: str = "http://localhost:6333",
        db_path: Optional[str] = None,
        blob_dir: Optional[str] = None,
        collection: str = "memories",
        provider_mode: str = "auto",
    ):
        self.speaker_id = speaker_id

        resolved_db_path = str(resolve_repo_relative_path(db_path, DEFAULT_MEMORY_DB_PATH))
        resolved_blob_dir = str(resolve_repo_relative_path(blob_dir, DEFAULT_MEMORY_BLOB_DIR))

        Path(resolved_db_path).parent.mkdir(parents=True, exist_ok=True)
        Path(resolved_blob_dir).mkdir(parents=True, exist_ok=True)

        self.config = MemoryConfig(
            provider_mode=provider_mode,
            qdrant_url=qdrant_url,
            qdrant_collection=collection,
            db_path=resolved_db_path,
            blob_dir=resolved_blob_dir,
        )

        self.explicit = ExplicitStore(self.config.db_path)
        self.semantic = SemanticStore(
            url=self.config.qdrant_url,
            collection=self.config.qdrant_collection,
            embedding_model=self.config.embedding_model,
        )
        self.graph = GraphStore(
            uri=self.config.graphiti_uri,
            user=self.config.graphiti_user,
            password=self.config.graphiti_password,
        )
        self.blobs = BlobStore(base_dir=self.config.blob_dir, use_s3=self.config.use_s3, bucket=self.config.s3_bucket)

        self.short_term = ShortTermBuffer(max_tokens=self.config.short_term_tokens)
        self.router = MemoryRouter(graph_store=self.graph)
        self.retrieval = RetrievalEngine(
            semantic_store=self.semantic,
            graph_store=self.graph,
            explicit_store=self.explicit,
            blob_store=self.blobs,
        )
        self.personalization = PersonalizationLayer(explicit_store=self.explicit)

        self.file_ingester = FileIngester(self.explicit, self.semantic, self.blobs)
        self.image_ingester = ImageIngester(self.explicit, self.semantic, self.blobs)
        self.audio_ingester = AudioIngester(self.explicit, self.semantic, self.blobs)
        self.link_ingester = LinkIngester(self.explicit, self.semantic, self.graph)
        self.meeting_ingester = MeetingIngester(self.explicit, self.semantic, self.graph, self.blobs)

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
        return self.retrieval.search(
            query=query,
            speaker_id=speaker_id or self.speaker_id,
            type_filter=type_filter,
            date_from=date_from,
            date_to=date_to,
            source_url=source_url,
            top_k=top_k,
        )

    def ingest(
        self,
        source_type: str,
        content: str,
        speaker_id: Optional[str] = None,
        date: Optional[str] = None,
        title: Optional[str] = None,
        participants: Optional[List[str]] = None,
    ) -> IngestResponse:
        sid = speaker_id or self.speaker_id

        if source_type == "link":
            return self.link_ingester.ingest(url=content, speaker_id=sid, date=date, title=title)

        if source_type == "meeting":
            return self.meeting_ingester.ingest_transcript(
                transcript=content,
                participants=participants or [sid],
                date=date,
                title=title,
            )

        try:
            raw = base64.b64decode(content)
        except Exception as exc:
            raise MemoryValidationError(
                "Invalid base64 payload for non-link ingestion source.",
                details={"source_type": source_type},
            ) from exc

        if source_type == "file":
            mime_type = "application/octet-stream"
            return self.file_ingester.ingest(raw, mime_type=mime_type, speaker_id=sid, date=date, title=title)
        if source_type == "image":
            return self.image_ingester.ingest(raw, speaker_id=sid, date=date, title=title)
        if source_type == "audio":
            return self.audio_ingester.ingest(raw, speaker_id=sid, date=date, title=title)

        raise MemoryValidationError(
            "Unsupported source_type.",
            details={"source_type": source_type},
        )

    def save(
        self,
        content: str,
        memory_type: MemoryType,
        speaker_id: Optional[str] = None,
        expires_at: Optional[str] = None,
    ) -> Dict[str, object]:
        if not content.strip():
            raise MemoryValidationError("Cannot save empty memory content.")

        record = MemoryRecord(
            id=str(uuid.uuid4()),
            type=memory_type,
            summary=content,
            speaker_id=speaker_id or self.speaker_id,
            created_at=datetime.utcnow(),
            metadata={"expires_at": expires_at} if expires_at else {},
        )
        try:
            self.explicit.insert(record)
        except Exception as exc:
            raise MemoryStoreError("Failed to persist memory record in explicit store.") from exc

        chunk_id = self.semantic.upsert(
            chunk_id=str(uuid.uuid4()),
            text=content,
            metadata={"memory_id": record.id, "speaker_id": record.speaker_id, "type": record.type.value},
        )
        record.chunk_ids = [chunk_id]
        self.explicit.update(record.id, {"chunk_ids": record.chunk_ids})
        return {"memory_id": record.id, "success": True}

    def _delete_record(self, record: MemoryRecord) -> Dict[str, object]:
        deleted_from: List[str] = []
        if record.chunk_ids and self.semantic.delete(record.chunk_ids):
            deleted_from.append("semantic")
        if record.graph_node_id and self.graph.delete_node(record.graph_node_id):
            deleted_from.append("graph")
        if record.blob_path and self.blobs.delete(record.blob_path):
            deleted_from.append("blob")
        if self.explicit.delete(record.id):
            deleted_from.append("explicit")
        return {"success": bool(deleted_from), "deleted_from": deleted_from}

    def delete(self, memory_id: str, speaker_id: Optional[str] = None) -> Dict[str, object]:
        owner = speaker_id or self.speaker_id
        record = self.explicit.get(memory_id)
        if not record:
            return {"success": False, "deleted_from": []}
        if record.speaker_id != owner:
            return {"success": False, "deleted_from": []}
        return self._delete_record(record)

    def update(self, memory_id: str, new_content: str, speaker_id: Optional[str] = None) -> Dict[str, bool]:
        owner = speaker_id or self.speaker_id
        record = self.explicit.get(memory_id)
        if not record or record.speaker_id != owner:
            return {"success": False}

        if record.chunk_ids:
            self.semantic.delete(record.chunk_ids)

        chunk_id = self.semantic.upsert(
            chunk_id=str(uuid.uuid4()),
            text=new_content,
            metadata={"memory_id": record.id, "speaker_id": record.speaker_id, "type": record.type.value},
        )
        ok = self.explicit.update(memory_id, {"summary": new_content, "chunk_ids": [chunk_id]})

        if ok and record.graph_node_id:
            try:
                self.graph.add_entity(
                    entity_id=record.graph_node_id,
                    entity_type=record.type.value,
                    properties={"memory_id": memory_id, "summary": new_content, "speaker_id": record.speaker_id},
                )
            except Exception:
                pass
        return {"success": bool(ok)}

    def update_by_query(
        self,
        query: str,
        new_content: str,
        speaker_id: Optional[str] = None,
        type_filter: Optional[MemoryType] = None,
    ) -> Dict[str, object]:
        owner = speaker_id or self.speaker_id
        results = self.search(query=query, speaker_id=owner, type_filter=type_filter, top_k=1)
        if not results.results:
            return {"success": False, "reason": "no_match"}
        target = results.results[0]
        updated = self.update(memory_id=target.memory_id, new_content=new_content, speaker_id=owner)
        return {"success": bool(updated.get("success")), "memory_id": target.memory_id}

    def delete_links(
        self,
        speaker_id: Optional[str] = None,
        domain: Optional[str] = None,
        delete_all: bool = False,
    ) -> Dict[str, object]:
        owner = speaker_id or self.speaker_id
        if not delete_all and not domain:
            raise MemoryValidationError("Provide domain or set delete_all=True for bulk link deletion.")

        rows = self.explicit.filter(speaker_id=owner, type_filter=MemoryType.LINK, limit=10000)
        deleted_ids: List[str] = []
        for row in rows:
            if not delete_all:
                src = row.source_url or ""
                if domain and domain not in src:
                    continue
            result = self._delete_record(row)
            if result.get("success"):
                deleted_ids.append(row.id)

        return {
            "success": True,
            "deleted_count": len(deleted_ids),
            "memory_ids": deleted_ids,
        }

    def get_user_model(self, speaker_id: Optional[str] = None) -> UserModel:
        return self.personalization.get_model(speaker_id or self.speaker_id)

    def get_short_term(self) -> list[dict]:
        return [
            {"speaker_id": t.speaker_id, "text": t.text, "timestamp": t.timestamp.isoformat()}
            for t in self.short_term.get_turns()
        ]

    def add_turn(self, speaker_id: str, text: str):
        self.short_term.add(speaker_id, text)

    def flush_session(self):
        sid = self.speaker_id
        transcript = self.short_term.to_text()
        if not transcript:
            return
        extracted = self.router.route_session(transcript=transcript, speaker_id=sid)
        saved: List[Dict[str, object]] = []
        for item in extracted:
            if item.get("confidence", 0) >= 0.7:
                mtype = item.get("memory_type", MemoryType.FACT)
                if isinstance(mtype, str):
                    mtype = MemoryType(mtype)
                saved.append(self.save(content=item["content"], memory_type=mtype, speaker_id=sid))
        self.personalization.update_from_session(speaker_id=sid, transcript=transcript, saved_facts=extracted)
        self.short_term.clear()


__all__ = [
    "MemorySystem",
    "MemoryType",
    "SearchResponse",
    "IngestResponse",
    "UserModel",
    "MemoryValidationError",
    "MemoryIngestionError",
    "MemoryStoreError",
]
