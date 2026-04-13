from __future__ import annotations

import base64
import os
from pathlib import Path
from typing import Optional


class BlobStore:
    """Local-disk blob store with a production-compatible interface."""

    def __init__(self, base_dir: str, use_s3: bool = False, bucket: Optional[str] = None):
        self.base_dir = Path(base_dir)
        self.use_s3 = use_s3
        self.bucket = bucket
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def save(self, memory_id: str, data: bytes, mime_type: str, filename: Optional[str] = None) -> str:
        ext = self._guess_extension(mime_type)
        file_name = filename or f"blob{ext}"
        rel_path = os.path.join(memory_id, file_name)
        full_path = self.base_dir / rel_path
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_bytes(data)
        return str(full_path)

    def load(self, blob_path: str) -> bytes:
        return Path(blob_path).read_bytes()

    def load_as_base64(self, blob_path: str) -> str:
        return base64.b64encode(self.load(blob_path)).decode("ascii")

    def delete(self, blob_path: str) -> bool:
        path = Path(blob_path)
        if not path.exists():
            return False
        path.unlink()
        return True

    def exists(self, blob_path: str) -> bool:
        return Path(blob_path).exists()

    @staticmethod
    def _guess_extension(mime_type: str) -> str:
        if not mime_type:
            return ".bin"
        if "json" in mime_type:
            return ".json"
        if "pdf" in mime_type:
            return ".pdf"
        if "png" in mime_type:
            return ".png"
        if "jpeg" in mime_type or "jpg" in mime_type:
            return ".jpg"
        if "webp" in mime_type:
            return ".webp"
        if "gif" in mime_type:
            return ".gif"
        if "audio" in mime_type and "wav" in mime_type:
            return ".wav"
        if "audio" in mime_type:
            return ".mp3"
        if "plain" in mime_type:
            return ".txt"
        return ".bin"
