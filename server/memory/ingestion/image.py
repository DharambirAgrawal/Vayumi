from __future__ import annotations

import io
import uuid
from datetime import datetime
from typing import Optional

from memory.models import IngestResponse, MemoryRecord, MemoryType
from memory.stores.blobs import BlobStore
from memory.stores.explicit import ExplicitStore
from memory.stores.semantic import SemanticStore


class ImageIngester:
    """Image ingest pipeline with descriptive text indexing."""

    def __init__(self, explicit_store: ExplicitStore, semantic_store: SemanticStore, blob_store: BlobStore):
        self.explicit_store = explicit_store
        self.semantic_store = semantic_store
        self.blob_store = blob_store

    def ingest(
        self,
        image_data: bytes,
        speaker_id: str,
        mime_type: str = "image/png",
        date: Optional[str] = None,
        title: Optional[str] = None,
    ) -> IngestResponse:
        description = self.describe(image_data=image_data, mime_type=mime_type)
        memory_id = str(uuid.uuid4())
        chunk_ids = []
        for chunk in [c.strip() for c in description.split(". ") if c.strip()]:
            chunk_id = str(uuid.uuid4())
            self.semantic_store.upsert(
                chunk_id=chunk_id,
                text=chunk,
                metadata={
                    "memory_id": memory_id,
                    "speaker_id": speaker_id,
                    "type": MemoryType.IMAGE.value,
                    "date": date,
                },
            )
            chunk_ids.append(chunk_id)

        blob_path = self.blob_store.save(memory_id=memory_id, data=image_data, mime_type=mime_type)
        record = MemoryRecord(
            id=memory_id,
            type=MemoryType.IMAGE,
            summary=title or description[:220],
            speaker_id=speaker_id,
            created_at=datetime.utcnow(),
            blob_path=blob_path,
            chunk_ids=chunk_ids,
            metadata={"date": date, "mime_type": mime_type, "title": title},
        )
        self.explicit_store.insert(record)
        return IngestResponse(memory_id=memory_id, store="image", chunk_count=len(chunk_ids), success=True)

    def describe(self, image_data: bytes, mime_type: str) -> str:
        if not image_data:
            return "Empty image payload received."

        details = [f"Image mime type: {mime_type}."]

        try:
            from PIL import Image, ImageStat

            with Image.open(io.BytesIO(image_data)) as img:
                width, height = img.size
                mode = img.mode
                fmt = img.format or "unknown"
                details.append(f"Format: {fmt}. Size: {width}x{height}. Mode: {mode}.")

                rgb = img.convert("RGB")
                stat = ImageStat.Stat(rgb)
                avg = [int(v) for v in stat.mean[:3]]
                brightness = int(sum(avg) / 3)
                tone = "dark" if brightness < 85 else "bright" if brightness > 170 else "balanced"
                details.append(
                    f"Average color approximately RGB({avg[0]}, {avg[1]}, {avg[2]}), overall lighting appears {tone}."
                )

                thumb = rgb.resize((64, 64))
                colors = thumb.getcolors(maxcolors=64 * 64) or []
                if colors:
                    colors.sort(key=lambda x: x[0], reverse=True)
                    top = colors[:3]
                    palette = ", ".join(f"RGB{c[1]}" for c in top)
                    details.append(f"Dominant color palette: {palette}.")
        except Exception:
            details.append("Pixel-level analysis unavailable in this runtime.")

        details.append("Use an external vision provider for OCR and detailed object reasoning when needed.")
        return " ".join(details)
