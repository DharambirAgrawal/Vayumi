from __future__ import annotations

import os

import lancedb
from lancedb.db import LanceDBConnection

from server.logger import get_logger
from server.memory.embeddings import embedding_dim

log = get_logger("db.lancedb")

_db: LanceDBConnection | None = None
FACTS_INDEX_TABLE = "facts_index"
MEETING_CHUNKS_TABLE = "meeting_chunks"


async def init_lancedb(lancedb_dir: str) -> LanceDBConnection:
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
    if MEETING_CHUNKS_TABLE not in table_names:
        db.create_table(
            MEETING_CHUNKS_TABLE,
            [
                {
                    "chunk_id": "__bootstrap__",
                    "meeting_id": "",
                    "user_id": "",
                    "speaker": "",
                    "ts_start": 0.0,
                    "ts_end": 0.0,
                    "text": "",
                    "embedding": [0.0] * embedding_dim(),
                }
            ],
        )
        table = db.open_table(MEETING_CHUNKS_TABLE)
        table.delete('chunk_id = "__bootstrap__"')
        log.info("lancedb.table_created", table=MEETING_CHUNKS_TABLE)
    log.info("lancedb.ok")
    _db = db
    return db


async def close_lancedb() -> None:
    global _db
    _db = None
    log.info("lancedb.closed")


def get_lancedb() -> LanceDBConnection:
    if _db is None:
        raise RuntimeError("LanceDB not initialized — call init_lancedb first")
    return _db


def escape_lancedb_str(value: str) -> str:
    return value.replace('"', '\\"').replace("'", "\\'")


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
    safe_id = escape_lancedb_str(fact_id)
    table.delete(f'fact_id = "{safe_id}"')
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


def upsert_meeting_chunk(
    *,
    chunk_id: str,
    meeting_id: str,
    user_id: str,
    speaker: str,
    ts_start: float,
    ts_end: float,
    text: str,
    embedding: list[float],
) -> None:
    db = get_lancedb()
    table = db.open_table(MEETING_CHUNKS_TABLE)
    safe_id = escape_lancedb_str(chunk_id)
    table.delete(f'chunk_id = "{safe_id}"')
    table.add(
        [
            {
                "chunk_id": chunk_id,
                "meeting_id": meeting_id,
                "user_id": user_id,
                "speaker": speaker,
                "ts_start": ts_start,
                "ts_end": ts_end,
                "text": text,
                "embedding": embedding,
            }
        ]
    )
