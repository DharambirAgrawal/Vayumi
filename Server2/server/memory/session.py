from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from server.db.postgres import get_pool
from server.logger import get_logger

log = get_logger("memory.session")


@dataclass(frozen=True)
class SessionState:
    id: str
    user_id: str
    client_meta: dict[str, Any]
    compressed_summary: str | None
    created_at: datetime
    last_seen_at: datetime


def _row_to_session(row: Any) -> SessionState:
    raw_meta = row["client_meta"]
    if isinstance(raw_meta, str):
        meta = json.loads(raw_meta)
    else:
        meta = raw_meta
    return SessionState(
        id=row["id"],
        user_id=row["user_id"],
        client_meta=meta,
        compressed_summary=row["compressed_summary"],
        created_at=row["created_at"],
        last_seen_at=row["last_seen_at"],
    )


@dataclass(frozen=True)
class TurnRecord:
    id: str
    session_id: str
    user_id: str
    role: str
    text: str
    created_at: datetime


async def load_or_create_session(
    user_id: str,
    session_id: str,
    client_meta: dict[str, Any] | None = None,
) -> SessionState:
    meta = client_meta or {}
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO sessions (id, user_id, client_meta, last_seen_at)
            VALUES ($1, $2, $3::jsonb, now())
            ON CONFLICT (id) DO UPDATE
            SET last_seen_at = now(),
                client_meta = COALESCE(sessions.client_meta, '{}'::jsonb) || EXCLUDED.client_meta
            RETURNING *
            """,
            session_id,
            user_id,
            json_dumps(meta),
        )
    assert row is not None
    return _row_to_session(row)


async def persist_session_snapshot(session: SessionState) -> None:
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE sessions
            SET last_seen_at = now(),
                client_meta = $2::jsonb,
                compressed_summary = $3
            WHERE id = $1
            """,
            session.id,
            json_dumps(session.client_meta),
            session.compressed_summary,
        )


async def append_turn(
    session_id: str,
    user_id: str,
    role: str,
    text: str,
) -> TurnRecord:
    turn_id = uuid.uuid4()
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO turns (id, session_id, user_id, role, text)
            VALUES ($1, $2, $3, $4, $5)
            RETURNING *
            """,
            turn_id,
            session_id,
            user_id,
            role,
            text,
        )
        await conn.execute(
            "UPDATE sessions SET last_seen_at = now() WHERE id = $1",
            session_id,
        )
    assert row is not None
    return TurnRecord(
        id=str(row["id"]),
        session_id=row["session_id"],
        user_id=row["user_id"],
        role=row["role"],
        text=row["text"],
        created_at=row["created_at"],
    )


async def recent_turns(session_id: str, limit: int = 8) -> list[TurnRecord]:
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT * FROM turns
            WHERE session_id = $1
            ORDER BY created_at DESC
            LIMIT $2
            """,
            session_id,
            limit,
        )
    records = [
        TurnRecord(
            id=str(row["id"]),
            session_id=row["session_id"],
            user_id=row["user_id"],
            role=row["role"],
            text=row["text"],
            created_at=row["created_at"],
        )
        for row in rows
    ]
    records.reverse()
    return records


async def compressed_history(session_id: str) -> str:
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT compressed_summary FROM sessions WHERE id = $1",
            session_id,
        )
    if row is None or not row["compressed_summary"]:
        return ""
    return str(row["compressed_summary"])


def json_dumps(value: Any) -> str:
    return json.dumps(value)
