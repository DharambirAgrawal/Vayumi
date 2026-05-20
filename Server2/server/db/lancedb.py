from __future__ import annotations

import os
from typing import Any

import lancedb

from server.logger import get_logger
from server.memory.embeddings import embedding_dim

log = get_logger("db.lancedb")

_db: Any = None
FACTS_INDEX_TABLE = "facts_index"


async def init_lancedb(lancedb_dir: str) -> Any:
    global _db
    os.makedirs(lancedb_dir, exist_ok=True)
    log.info("lancedb.connecting", dir=lancedb_dir)
    db = lancedb.connect(lancedb_dir)
    table_names = db.table_names()
    if "_ping" not in table_names:
        db.create_table("_ping", [{"ok": 1}])
    if FACTS_INDEX_TABLE not in table_names:
        db.create_table(
            FACTS_INDEX_TABLE,
            [
                {
                    "fact_id": "__bootstrap__",
                    "user_id": "",
                    "key": "",
                    "value_text": "",
                    "embedding": [0.0] * embedding_dim(),
                }
            ],
        )
        table = db.open_table(FACTS_INDEX_TABLE)
        table.delete('fact_id = "__bootstrap__"')
        log.info("lancedb.table_created", table=FACTS_INDEX_TABLE)
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


def upsert_fact_embedding(
    *,
    fact_id: str,
    user_id: str,
    key: str,
    value_text: str,
    embedding: list[float],
) -> None:
    db = get_lancedb()
    table = db.open_table(FACTS_INDEX_TABLE)
    table.delete(f'fact_id = "{fact_id}"')
    table.add(
        [
            {
                "fact_id": fact_id,
                "user_id": user_id,
                "key": key,
                "value_text": value_text,
                "embedding": embedding,
            }
        ]
    )
