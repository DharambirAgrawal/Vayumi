from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from server.config import get_settings
from server.db.lancedb import close_lancedb, init_lancedb
from server.db.postgres import close_postgres, init_postgres
from server.db.redis import close_redis, init_redis, init_server1_redis
from server.logger import get_logger, setup_logging
from server.transport.ws import ws_endpoint

log = get_logger("app")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    app.state.settings = settings

    setup_logging(log_level=settings.log_level, is_dev=settings.is_dev)

    log.info(
        "app.starting",
        env=settings.app_env,
        port=settings.port,
    )

    pool = await init_postgres(settings.database_url)

    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO server_health (id, last_boot)
            VALUES (1, $1)
            ON CONFLICT (id) DO UPDATE SET last_boot = $1
            """,
            datetime.now(timezone.utc),
        )

    await init_redis(settings.redis_url)

    if settings.server1_redis_url:
        await init_server1_redis(settings.server1_redis_url)
    elif settings.is_dev:
        log.warning("app.server1_redis_skipped", reason="SERVER1_REDIS_URL not set (dev mode)")

    await init_lancedb(settings.lancedb_dir)

    if settings.is_dev and not settings.jwt_public_key:
        log.info("app.dev_auth_bypass", msg="dev mode: auth bypass enabled")

    log.info("app.ready")

    yield

    log.info("app.shutting_down")
    await close_lancedb()
    await close_redis()
    await close_postgres()
    log.info("app.stopped")


app = FastAPI(title="Vayumi Server 2", version="0.1.0", lifespan=lifespan)
app.add_api_websocket_route("/ws/v1/session", ws_endpoint)
app.mount("/", StaticFiles(directory="web-client", html=True), name="web-client")
