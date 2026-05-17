from __future__ import annotations

import redis.asyncio as aioredis

from server.logger import get_logger

log = get_logger("db.redis")

_client: aioredis.Redis | None = None
_server1_client: aioredis.Redis | None = None


async def init_redis(redis_url: str) -> aioredis.Redis:
    global _client
    log.info("redis.connecting", url=redis_url)
    client = aioredis.from_url(redis_url, decode_responses=True)
    await client.ping()
    log.info("redis.ok")
    _client = client
    return client


async def init_server1_redis(server1_redis_url: str) -> aioredis.Redis:
    global _server1_client
    log.info("redis.server1.connecting", url=server1_redis_url)
    client = aioredis.from_url(server1_redis_url, decode_responses=True)
    await client.ping()
    log.info("redis.server1.ok")
    _server1_client = client
    return client


async def close_redis() -> None:
    global _client, _server1_client
    if _client is not None:
        await _client.aclose()
        _client = None
    if _server1_client is not None:
        await _server1_client.aclose()
        _server1_client = None
    log.info("redis.closed")


def get_redis() -> aioredis.Redis:
    if _client is None:
        raise RuntimeError("Redis not initialized — call init_redis first")
    return _client


def get_server1_redis() -> aioredis.Redis | None:
    return _server1_client
