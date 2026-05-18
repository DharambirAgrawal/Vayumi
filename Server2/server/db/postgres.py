from __future__ import annotations

from typing import TYPE_CHECKING

import asyncpg

from server.logger import get_logger

if TYPE_CHECKING:
    pass

log = get_logger("db.postgres")

SCHEMA_SQL = """\
CREATE TABLE IF NOT EXISTS server_health (
    id SMALLINT PRIMARY KEY DEFAULT 1,
    last_boot TIMESTAMPTZ NOT NULL,
    CHECK (id = 1)
);
"""

_pool: asyncpg.Pool | None = None


async def init_postgres(database_url: str) -> asyncpg.Pool:
    global _pool
    log.info("postgres.connecting", url=database_url.split("@")[-1])
    pool = await asyncpg.create_pool(
        database_url,
        min_size=2,
        max_size=10,
    )
    assert pool is not None
    async with pool.acquire() as conn:
        await conn.execute(SCHEMA_SQL)
    log.info("postgres.ok", msg="schema migrated")
    _pool = pool
    return pool


async def close_postgres() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None
        log.info("postgres.closed")


def get_pool() -> asyncpg.Pool:
    if _pool is None:
        raise RuntimeError("Postgres pool not initialized — call init_postgres first")
    return _pool
