from __future__ import annotations

import os
from pathlib import Path
from typing import Optional


ENV_MEMORY_DB_PATH = "MEMORY_DB_PATH"
ENV_MEMORY_BLOB_DIR = "MEMORY_BLOB_DIR"
ENV_MEMORY_COLLECTION = "MEMORY_COLLECTION"
ENV_MEMORY_PROVIDER_MODE = "MEMORY_PROVIDER_MODE"
ENV_QDRANT_URL = "QDRANT_URL"

DEFAULT_QDRANT_URL = "http://localhost:6333"
DEFAULT_MEMORY_COLLECTION = "memories"
DEFAULT_MEMORY_PROVIDER_MODE = "auto"

REPO_ROOT = Path(__file__).resolve().parents[2]
MEMORY_DATA_ROOT = REPO_ROOT / "data" / "memory"
DEFAULT_MEMORY_DB_PATH = MEMORY_DATA_ROOT / "memory.db"
DEFAULT_MEMORY_BLOB_DIR = MEMORY_DATA_ROOT / "blobs"
DEFAULT_MEMORY_ML_DIR = MEMORY_DATA_ROOT / "ml"


def resolve_repo_relative_path(configured: Optional[str], default_path: Path) -> Path:
    if not configured or not configured.strip():
        return default_path

    path = Path(configured.strip()).expanduser()
    if not path.is_absolute():
        path = REPO_ROOT / path
    return path.resolve()


def runtime_memory_settings() -> dict[str, str]:
    db_path = resolve_repo_relative_path(os.getenv(ENV_MEMORY_DB_PATH), DEFAULT_MEMORY_DB_PATH)
    blob_dir = resolve_repo_relative_path(os.getenv(ENV_MEMORY_BLOB_DIR), DEFAULT_MEMORY_BLOB_DIR)

    return {
        "qdrant_url": os.getenv(ENV_QDRANT_URL, DEFAULT_QDRANT_URL),
        "db_path": str(db_path),
        "blob_dir": str(blob_dir),
        "collection": os.getenv(ENV_MEMORY_COLLECTION, DEFAULT_MEMORY_COLLECTION),
        "provider_mode": os.getenv(ENV_MEMORY_PROVIDER_MODE, DEFAULT_MEMORY_PROVIDER_MODE),
    }
