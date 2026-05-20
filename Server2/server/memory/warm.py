from __future__ import annotations

import json

from server.db.postgres import get_pool
from server.db.redis import get_redis
from server.logger import get_logger

log = get_logger("memory.warm")

WARM_KEY_PREFIXES: tuple[str, ...] = (
    "name",
    "city",
    "email.",
    "comm_style.",
    "relationships.",
    "integrations.",
    "preferences.",
)

_WARM_CACHE_TTL_SECONDS = 600
_dirty_users: set[str] = set()


def affects_warm_profile(key: str) -> bool:
    if key in WARM_KEY_PREFIXES:
        return True
    return any(key.startswith(prefix) for prefix in WARM_KEY_PREFIXES if prefix.endswith("."))


async def mark_dirty(user_id: str) -> None:
    _dirty_users.add(user_id)
    redis = get_redis()
    await redis.delete(_warm_cache_key(user_id))
    log.debug("memory.warm_dirty", user_id=user_id)


async def build_warm_profile(user_id: str) -> str:
    if user_id not in _dirty_users:
        cached = await _read_warm_cache(user_id)
        if cached is not None:
            return cached

    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT key, value FROM facts
            WHERE user_id = $1 AND active = true
            ORDER BY key ASC
            """,
            user_id,
        )

    lines: list[str] = []
    for row in rows:
        key = row["key"]
        if not affects_warm_profile(key):
            continue
        raw_value = row["value"]
        if isinstance(raw_value, str):
            value = json.loads(raw_value)
        else:
            value = raw_value
        if isinstance(value, str):
            rendered = value
        else:
            rendered = json.dumps(value, ensure_ascii=False)
        lines.append(f"- {key}: {rendered}")

    if not lines:
        block = "Known profile facts: (none yet)"
    else:
        block = "Known profile facts:\n" + "\n".join(lines)

    block = _truncate_warm_block(block, max_chars=2400)
    await _write_warm_cache(user_id, block)
    _dirty_users.discard(user_id)
    return block


def _truncate_warm_block(text: str, *, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 3].rstrip() + "..."


def _warm_cache_key(user_id: str) -> str:
    return f"warm_cache:{user_id}"


async def _read_warm_cache(user_id: str) -> str | None:
    redis = get_redis()
    return await redis.get(_warm_cache_key(user_id))


async def _write_warm_cache(user_id: str, block: str) -> None:
    redis = get_redis()
    await redis.set(_warm_cache_key(user_id), block, ex=_WARM_CACHE_TTL_SECONDS)
