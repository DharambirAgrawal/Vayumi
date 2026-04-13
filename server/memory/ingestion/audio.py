from __future__ import annotations

import os
import tempfile
import uuid
from datetime import datetime
from typing import Optional

from memory.models import IngestResponse, MemoryRecord, MemoryType
from memory.stores.blobs import BlobStore
from memory.stores.explicit import ExplicitStore
from memory.stores.semantic import SemanticStore


class AudioIngester:
    """Audio ingest pipeline with pluggable transcription."""

    def __init__(self, explicit_store: ExplicitStore, semantic_store: SemanticStore, blob_store: BlobStore):
        self.explicit_store = explicit_store
        self.semantic_store = semantic_store
        self.blob_store = blob_store

    def ingest(
        self,
        audio_data: bytes,
        speaker_id: str,
        mime_type: str = "audio/mp3",
        date: Optional[str] = None,
        title: Optional[str] = None,
    ) -> IngestResponse:
        transcript = self.transcribe(audio_data)
        memory_id = str(uuid.uuid4())
        chunk_ids = []
        for sentence in [s.strip() for s in transcript.split(".") if s.strip()]:
            chunk_id = str(uuid.uuid4())
            self.semantic_store.upsert(
                chunk_id=chunk_id,
                text=sentence,
                metadata={
                    "memory_id": memory_id,
                    "speaker_id": speaker_id,
                    "type": MemoryType.AUDIO.value,
                    "date": date,
                },
            )
            chunk_ids.append(chunk_id)

        blob_path = self.blob_store.save(memory_id=memory_id, data=audio_data, mime_type=mime_type)
        record = MemoryRecord(
            id=memory_id,
            type=MemoryType.AUDIO,
            summary=title or transcript[:220],
            speaker_id=speaker_id,
            created_at=datetime.utcnow(),
            blob_path=blob_path,
            chunk_ids=chunk_ids,
            metadata={"date": date, "mime_type": mime_type, "title": title},
        )
        self.explicit_store.insert(record)
        return IngestResponse(memory_id=memory_id, store="audio", chunk_count=len(chunk_ids), success=True)

    def transcribe(self, audio_data: bytes) -> str:
        if not audio_data:
            return ""

        if os.getenv("MEMORY_DISABLE_WHISPER", "0") == "1":
            approx_secs = max(1, len(audio_data) // 32000)
            return (
                "Audio received; Whisper transcription disabled by configuration. "
                f"Captured approximately {approx_secs} seconds of audio data."
            )

        try:
            import whisper

            model_name = os.getenv("MEMORY_WHISPER_MODEL", "base")
            model = whisper.load_model(model_name)
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=True) as fp:
                fp.write(audio_data)
                fp.flush()
                result = model.transcribe(fp.name, fp16=False)
                text = str(result.get("text", "")).strip()
                if text:
                    return text
        except Exception:
            pass

        approx_secs = max(1, len(audio_data) // 32000)
        return (
            "Audio received but transcription is unavailable in the current runtime. "
            f"Captured approximately {approx_secs} seconds of audio data."
        )
