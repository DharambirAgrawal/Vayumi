from __future__ import annotations

import io
import json
import uuid
from datetime import datetime
from typing import List, Optional

from memory.models import IngestResponse, MemoryRecord, MemoryType
from memory.stores.blobs import BlobStore
from memory.stores.explicit import ExplicitStore
from memory.stores.semantic import SemanticStore


class FileIngester:
    """File ingest pipeline for structured and unstructured text."""

    def __init__(self, explicit_store: ExplicitStore, semantic_store: SemanticStore, blob_store: BlobStore):
        self.explicit_store = explicit_store
        self.semantic_store = semantic_store
        self.blob_store = blob_store

    def ingest(
        self,
        file_data: bytes,
        mime_type: str,
        speaker_id: str,
        date: Optional[str] = None,
        title: Optional[str] = None,
    ) -> IngestResponse:
        text = self.extract(file_data=file_data, mime_type=mime_type)
        chunks = self.chunk(text=text, chunk_size=400, overlap=200)
        memory_id = str(uuid.uuid4())
        chunk_ids: List[str] = []
        for chunk in chunks:
            chunk_id = str(uuid.uuid4())
            self.semantic_store.upsert(
                chunk_id=chunk_id,
                text=chunk,
                metadata={
                    "memory_id": memory_id,
                    "speaker_id": speaker_id,
                    "type": MemoryType.FILE.value,
                    "date": date,
                },
            )
            chunk_ids.append(chunk_id)

        blob_path = self.blob_store.save(memory_id=memory_id, data=file_data, mime_type=mime_type)
        record = MemoryRecord(
            id=memory_id,
            type=MemoryType.FILE,
            summary=title or text[:220],
            speaker_id=speaker_id,
            created_at=datetime.utcnow(),
            blob_path=blob_path,
            chunk_ids=chunk_ids,
            metadata={"date": date, "mime_type": mime_type, "title": title},
        )
        self.explicit_store.insert(record)
        return IngestResponse(memory_id=memory_id, store="file", chunk_count=len(chunk_ids), success=True)

    def extract(self, file_data: bytes, mime_type: str) -> str:
        if mime_type == "application/json":
            try:
                obj = json.loads(file_data.decode("utf-8", errors="ignore"))
                return json.dumps(obj, indent=2)
            except Exception:
                return file_data.decode("utf-8", errors="ignore")

        if mime_type == "application/pdf":
            try:
                import pdfplumber

                pages: List[str] = []
                with pdfplumber.open(io.BytesIO(file_data)) as pdf:
                    for page in pdf.pages:
                        pages.append(page.extract_text() or "")
                text = "\n\n".join(pages).strip()
                if text:
                    return text
            except Exception:
                pass

        if mime_type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
            try:
                from docx import Document

                doc = Document(io.BytesIO(file_data))
                text = "\n".join(p.text for p in doc.paragraphs if p.text).strip()
                if text:
                    return text
            except Exception:
                pass

        if mime_type in {"text/csv", "application/csv"}:
            try:
                import pandas as pd

                df = pd.read_csv(io.BytesIO(file_data))
                return df.to_markdown(index=False)
            except Exception:
                pass

        if mime_type.startswith("text/"):
            return file_data.decode("utf-8", errors="ignore")

        return file_data.decode("utf-8", errors="ignore")

    def chunk(self, text: str, chunk_size: int = 400, overlap: int = 200) -> List[str]:
        words = text.split()
        if not words:
            return []
        chunks: List[str] = []
        i = 0
        step = max(1, chunk_size - overlap)
        while i < len(words):
            chunk_words = words[i : i + chunk_size]
            chunks.append(" ".join(chunk_words))
            i += step
        return chunks
