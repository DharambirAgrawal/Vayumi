from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import asyncpg

from server.db.lancedb import upsert_fact_embedding
from server.db.postgres import get_pool
from server.logger import get_logger
from server.memory.embeddings import embed_text_async
from server.memory.warm import affects_warm_profile, mark_dirty

log = get_logger("memory.facts")


@dataclass(frozen=True)
class FactRecord:
    id: str
    user_id: str
    key: str
    value: Any
    active: bool
    source: str
    confidence: float
    created_at: datetime
    superseded_at: datetime | None = None
    superseded_by: str | None = None


def _row_to_record(row: asyncpg.Record) -> FactRecord:
    raw_value = row["value"]
    if isinstance(raw_value, str):
        value: Any = json.loads(raw_value)
    else:
        value = raw_value
    return FactRecord(
        id=str(row["id"]),
        user_id=row["user_id"],
        key=row["key"],
        value=value,
        active=row["active"],
        source=row["source"],
        confidence=float(row["confidence"]),
        created_at=row["created_at"],
        superseded_at=row["superseded_at"],
        superseded_by=str(row["superseded_by"]) if row["superseded_by"] else None,
    )


async def set_fact(
    user_id: str,
    key: str,
    value: Any,
    source: str,
    *,
    confidence: float = 1.0,
) -> FactRecord:
    new_id = uuid.uuid4()
    value_json = json.dumps(value)
    pool = get_pool()

    async with pool.acquire() as conn:
        async with conn.transaction():
            prior = await conn.fetchrow(
                """
                SELECT id FROM facts
                WHERE user_id = $1 AND key = $2 AND active = true
                """,
                user_id,
                key,
            )
            if prior is not None:
                await conn.execute(
                    """
                    UPDATE facts
                    SET active = false,
                        superseded_at = now(),
                        superseded_by = $1
                    WHERE id = $2
                    """,
                    new_id,
                    prior["id"],
                )

            row = await conn.fetchrow(
                """
                INSERT INTO facts (
                    id, user_id, key, value, active, source, confidence
                )
                VALUES ($1, $2, $3, $4::jsonb, true, $5, $6)
                RETURNING *
                """,
                new_id,
                user_id,
                key,
                value_json,
                source,
                confidence,
            )

    assert row is not None
    record = _row_to_record(row)
    value_text = _value_to_text(value)
    embedding = await embed_text_async(f"{key}: {value_text}")
    upsert_fact_embedding(
        fact_id=record.id,
        user_id=user_id,
        key=key,
        value_text=value_text,
        embedding=embedding,
    )
    if affects_warm_profile(key):
        await mark_dirty(user_id)

    log.info(
        "memory.fact_set",
        user_id=user_id,
        key=key,
        fact_id=record.id,
        source=source,
    )
    return record


async def get_fact(user_id: str, key: str) -> FactRecord | None:
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT * FROM facts
            WHERE user_id = $1 AND key = $2 AND active = true
            """,
            user_id,
            key,
        )
    if row is None:
        return None
    return _row_to_record(row)


async def get_chain(user_id: str, key: str) -> list[FactRecord]:
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT * FROM facts
            WHERE user_id = $1 AND key = $2
            ORDER BY created_at DESC
            """,
            user_id,
            key,
        )
    return [_row_to_record(row) for row in rows]


def _value_to_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False)
