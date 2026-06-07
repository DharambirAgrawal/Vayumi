from __future__ import annotations

import asyncio
import uuid
from typing import TYPE_CHECKING

from starlette.websockets import WebSocket

from server.logger import get_logger
from server.transport.queue_types import PendingChatDelivery, QueuedChat
from server.transport.session_busy import playback_blocks_voice, session_busy
from server.voice.respond_via import compute_respond_via

if TYPE_CHECKING:
    from server.config import Settings
    from server.engine.pool import EnginePool
    from server.transport.session_registry import UserSession

log = get_logger("transport.chat_queue")


def enqueue_chat(
    session: UserSession,
    text: str,
    *,
    prefer_voice: bool = True,
) -> None:
    """Single-slot queue (depth=1): replace any pending typed chat."""
    stripped = text.strip()
    if not stripped:
        return
    session.queued_chat = QueuedChat(text=stripped, prefer_voice=prefer_voice)
    log.debug(
        "chat_queue.enqueued",
        user_id=session.user_id,
        chars=len(stripped),
        prefer_voice=prefer_voice,
    )


async def wait_until_deliverable(
    session: UserSession,
    *,
    want_voice: bool,
    timeout_s: float = 30.0,
) -> bool:
    """Wait until server FSM is idle and (if voice) client playback is idle."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_s
    while loop.time() < deadline:
        if not session_busy(session):
            if not want_voice or not playback_blocks_voice(session):
                return True
        await asyncio.sleep(0.05)
    return False


async def try_deliver_pending_chat(
    websocket: WebSocket,
    session: UserSession,
    settings: Settings,
) -> bool:
    """Speak a turn that was computed in the background while TTS was playing."""
    pending = session.pending_chat_delivery
    if pending is None:
        return False
    if session.turn_task and not session.turn_task.done():
        return False
    if pending.prefer_voice and playback_blocks_voice(session):
        return False

    from server.voice.delivery import deliver_turn_output
    session.pending_chat_delivery = None
    voice = websocket.app.state.voice
    session.interrupt.begin_thinking(pending.turn_id)
    try:
        delay = (
            settings.aec_client_suppression_delay_ms
            if session.capabilities.get("aec")
            else settings.self_echo_suppression_delay_ms
        )
        await deliver_turn_output(
            websocket,
            turn_id=pending.turn_id,
            assistant_text=pending.assistant_text,
            respond_via=pending.respond_via,
            interrupt=session.interrupt,
            tts=voice["tts"],
            suppression_delay_ms=delay,
            stream_captions_during_llm=False,
            streaming_pipeline=None,
        )
        log.info(
            "chat_queue.delivered_pending",
            user_id=session.user_id,
            turn_id=pending.turn_id,
            chars=len(pending.assistant_text),
        )
        return True
    finally:
        session.interrupt.finish_turn()


async def start_background_chat_compute(
    websocket: WebSocket,
    session: UserSession,
    settings: Settings,
    engine_pool: EnginePool,
) -> None:
    """Run LLM + tools immediately; defer TTS until playback is idle."""
    if session.queued_chat is None:
        return
    if session.queued_compute_task and not session.queued_compute_task.done():
        session.queued_compute_task.cancel()
        try:
            await session.queued_compute_task
        except asyncio.CancelledError:
            pass

    item = session.queued_chat
    session.queued_chat = None

    async def _compute() -> None:
        from server.transport.ws import make_activity_event_emitter

        tid = str(uuid.uuid4())
        try:
            decision = compute_respond_via(
                capabilities_tts=session.capabilities.get("tts", True),
                client_state=session.client_control,
                input_kind="chat",
                force_voice=item.prefer_voice,
            )
            tool_runner = getattr(websocket.app.state, "tool_runner", None)
            activity_emitter = make_activity_event_emitter(session)
            output = await session.supervisor.run_turn(
                item.text,
                engine_pool=engine_pool,
                on_token=None,
                input_kind="chat",
                computed_respond_via="chat_only",
                turn_id=tid,
                tool_runner=tool_runner,
                on_tool_event=activity_emitter,
                on_task_event=activity_emitter,
                on_status_caption=None,
            )
            deliver_via = (
                decision.respond_via
                if not playback_blocks_voice(session)
                else (
                    "voice_and_chat"
                    if item.prefer_voice and session.capabilities.get("tts", True)
                    else "chat_only"
                )
            )
            session.pending_chat_delivery = PendingChatDelivery(
                turn_id=output.turn_id,
                assistant_text=output.assistant_text,
                respond_via=deliver_via,
                prefer_voice=item.prefer_voice,
            )
            log.info(
                "chat_queue.compute_done",
                user_id=session.user_id,
                turn_id=output.turn_id,
                chars=len(output.assistant_text),
            )
            await try_deliver_pending_chat(websocket, session, settings)
            if session.queued_chat is not None:
                await start_background_chat_compute(
                    websocket, session, settings, engine_pool
                )
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception(
                "chat_queue.compute_failed",
                user_id=session.user_id,
                text=item.text[:80],
            )
            enqueue_chat(session, item.text, prefer_voice=item.prefer_voice)
        finally:
            session.queued_compute_task = None

    session.queued_compute_task = asyncio.create_task(
        _compute(),
        name=f"queued-compute-{session.user_id}",
    )


async def _run_queued_turn(
    websocket: WebSocket,
    session: UserSession,
    item: QueuedChat,
    settings: Settings,
    engine_pool: EnginePool,
    *,
    run_chat_turn: object,
) -> None:
    try:
        if session.pending_chat_delivery is not None:
            if await try_deliver_pending_chat(websocket, session, settings):
                return
        ready = await wait_until_deliverable(
            session, want_voice=item.prefer_voice
        )
        if not ready:
            log.warning(
                "chat_queue.deliver_timeout",
                user_id=session.user_id,
                text=item.text[:80],
            )
            enqueue_chat(session, item.text, prefer_voice=item.prefer_voice)
            await start_background_chat_compute(
                websocket, session, settings, engine_pool
            )
            return
        await run_chat_turn(  # type: ignore[operator]
            websocket,
            session,
            item.text,
            settings,
            engine_pool,
            force_voice=item.prefer_voice,
        )
    finally:
        session.queued_chat_task = None


async def drain_chat_queue(
    session: UserSession,
    websocket: WebSocket,
    engine_pool: EnginePool,
    *,
    run_chat_turn: object,
) -> None:
    """Deliver pending background turns or start queued compute."""
    settings: Settings = websocket.app.state.settings
    if await try_deliver_pending_chat(websocket, session, settings):
        return
    if session.queued_chat is not None:
        await start_background_chat_compute(
            websocket, session, settings, engine_pool
        )
        return
    if session.queued_chat_task and not session.queued_chat_task.done():
        return
    if session.queued_chat is None:
        return
    item = session.queued_chat
    session.queued_chat = None
    session.queued_chat_task = asyncio.create_task(
        _run_queued_turn(
            websocket,
            session,
            item,
            settings,
            engine_pool,
            run_chat_turn=run_chat_turn,
        ),
        name=f"queued-chat-drain-{session.user_id}",
    )


async def drain_queued_chat(
    session: UserSession,
    websocket: WebSocket,
    engine_pool: EnginePool,
    *,
    run_chat_turn: object,
) -> None:
    await drain_chat_queue(
        session, websocket, engine_pool, run_chat_turn=run_chat_turn
    )
