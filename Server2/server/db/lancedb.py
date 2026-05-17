from __future__ import annotations

import os
from typing import Any

import lancedb

from server.logger import get_logger

log = get_logger("db.lancedb")

_db: Any = None


async def init_lancedb(lancedb_dir: str) -> Any:
    global _db
    os.makedirs(lancedb_dir, exist_ok=True)
    log.info("lancedb.connecting", dir=lancedb_dir)
    db = lancedb.connect(lancedb_dir)
    table_names = db.table_names()
    if "_ping" not in table_names:
        db.create_table("_ping", [{"ok": 1}])
    log.info("lancedb.ok")
    _db = db
    return db


async def close_lancedb() -> None:
    global _db
    _db = None
    log.info("lancedb.closed")


def get_lancedb() -> Any:
    if _db is None:
        raise RuntimeError("LanceDB not initialized — call init_lancedb first")
    return _db
