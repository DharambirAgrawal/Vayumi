from __future__ import annotations

from pathlib import Path

import asyncpg

from server.logger import get_logger

log = get_logger("db.postgres")

_SCHEMA_PATH = Path(__file__).with_name("schema.sql")

_pool: asyncpg.Pool | None = None


async def init_postgres(
    database_url: str,
    *,
    min_size: int = 2,
    max_size: int = 10,
) -> asyncpg.Pool:
    global _pool
    log.info("postgres.connecting", url=database_url.split("@")[-1])
    pool = await asyncpg.create_pool(
        database_url,
        min_size=min_size,
        max_size=max_size,
        statement_cache_size=0,
    )
    assert pool is not None
    schema_sql = _SCHEMA_PATH.read_text(encoding="utf-8")
    async with pool.acquire() as conn:
        await conn.execute(schema_sql)
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
