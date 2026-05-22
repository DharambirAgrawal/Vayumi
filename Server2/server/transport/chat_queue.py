from __future__ import annotations

import asyncio

from starlette.websockets import WebSocket

from server.config import Settings
from server.engine.pool import EnginePool
from server.transport.session_registry import UserSession


async def drain_queued_chat(
    session: UserSession,
    websocket: WebSocket,
    engine_pool: EnginePool,
    *,
    run_chat_turn: object,
) -> None:
    if session.queued_chat_text and (
        session.queued_chat_task is None or session.queued_chat_task.done()
    ):
        settings: Settings = websocket.app.state.settings
        text = session.queued_chat_text
        session.queued_chat_text = None
        session.queued_chat_task = asyncio.create_task(
            run_chat_turn(websocket, session, text, settings, engine_pool),  # type: ignore[operator]
            name=f"queued-chat-drain-{session.user_id}",
        )
