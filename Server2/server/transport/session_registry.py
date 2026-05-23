from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from starlette.websockets import WebSocket, WebSocketState

from server.logger import get_logger
from server.orchestrator.supervisor import Supervisor
from server.transport.client_control import ClientControlSession
from server.transport.protocol import EventMessage, EventPayload, serialize_server_message
from server.voice.interrupt import InterruptController

log = get_logger("transport.session_registry")

SESSION_SINGLETON_CLOSE_CODE = 4001


@dataclass
class UserSession:
    user_id: str
    session_id: str
    supervisor: Supervisor
    interrupt: InterruptController = field(default_factory=InterruptController)
    client_control: ClientControlSession = field(default_factory=ClientControlSession)
    capabilities: dict[str, bool] = field(default_factory=dict)
    websocket: WebSocket | None = None
    turn_task: asyncio.Task[None] | None = None
    queued_chat_text: str | None = None
    queued_chat_task: asyncio.Task[None] | None = None
    accumulated_partial: str = ""
    voice_capture_active: bool = False
    voice_chunks: list[bytes] = field(default_factory=list)
    pending_voice_chunks: list[bytes] | None = None
    turn_llm_persisted: bool = False
    surfaced_signal_keys: set[str] = field(default_factory=set)
    last_proactive_at: float | None = None
    notifier_inflight: bool = False

    def attach_transport(self, websocket: WebSocket) -> None:
        self.websocket = websocket

    def detach_transport(self) -> None:
        self.websocket = None

    def task_board_snapshot(self) -> dict[str, object]:
        return self.supervisor.task_board.snapshot()


_registry: dict[str, UserSession] = {}


def get_user_session(user_id: str) -> UserSession | None:
    return _registry.get(user_id)


def iter_user_sessions() -> list[UserSession]:
    return list(_registry.values())


async def enforce_session_singleton(
    *,
    user_id: str,
    session_id: str,
    new_ws: WebSocket,
    hello_session_id: str | None,
    close_code: int = SESSION_SINGLETON_CLOSE_CODE,
) -> tuple[UserSession, bool]:
    """
    One Supervisor per user_id. Supersedes any live WebSocket for that user.
    Returns (session, resumed).
    """
    existing = _registry.get(user_id)
    resumed = existing is not None

    if existing is not None and existing.websocket is not None:
        old_ws = existing.websocket
        if old_ws.client_state == WebSocketState.CONNECTED:
            event = EventMessage(
                payload=EventPayload(
                    kind="session_superseded",
                    task_id="",
                    summary="new_device",
                ),
            )
            try:
                await old_ws.send_text(serialize_server_message(event))
            except Exception as exc:
                log.warning("session_registry.supersede_send_failed", error=str(exc))
            try:
                await old_ws.close(code=close_code, reason="session_superseded")
            except Exception as exc:
                log.warning("session_registry.supersede_close_failed", error=str(exc))
        existing.detach_transport()

    if existing is not None:
        existing.attach_transport(new_ws)
        if hello_session_id:
            existing.session_id = hello_session_id
            existing.supervisor.session_id = hello_session_id
        session = existing
    else:
        sid = hello_session_id or session_id
        session = UserSession(
            user_id=user_id,
            session_id=sid,
            supervisor=Supervisor(user_id=user_id, session_id=sid),
        )
        session.attach_transport(new_ws)
        _registry[user_id] = session

    await session.supervisor.ensure_session(
        client_meta={"capabilities": session.capabilities},
    )
    log.info(
        "session_registry.attached",
        user_id=user_id,
        session_id=session.session_id,
        resumed=resumed,
    )
    return session, resumed


def remove_user_session(user_id: str) -> None:
    _registry.pop(user_id, None)


def clear_registry_for_tests() -> None:
    _registry.clear()
