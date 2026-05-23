from __future__ import annotations

import asyncio
import uuid

from starlette.websockets import WebSocket, WebSocketState

from server.config import Settings
from server.engine.pool import EnginePool
from server.logger import get_logger
from server.memory.session import append_turn, recent_turns
from server.orchestrator.task_board import TaskRow
from server.transport.session_registry import UserSession
from server.voice.delivery import deliver_turn_output
from server.voice.respond_via import compute_respond_via

log = get_logger("orchestrator.background_notify")


def format_background_done_block(row: TaskRow) -> str:
    summary = (row.result_summary or row.latest_step or "").strip()
    return (
        f'[BACKGROUND_TASK_DONE task_id={row.task_id} capability={row.capability} '
        f'goal="{row.goal}"]\n{summary}\n\n'
        "The user already heard your quick answers for other parts of this request "
        "(e.g. weather). ONLY summarize this background task — do not repeat weather "
        "or other topics. Open with a short line that the deep research is ready, then "
        "3–5 spoken sentences from the findings above. No [DELEGATE]."
    )


def schedule_background_delivery(
    session: UserSession,
    task_id: str,
    *,
    engine_pool: EnginePool,
    settings: Settings,
) -> None:
    """Fire-and-forget: Main speaks when a research/background task reaches DONE."""
    row = session.supervisor.task_board.get(task_id)
    if row is None or row.status != "done" or not (row.result_summary or "").strip():
        return
    if row.result_summary and row.result_summary.strip().lower() == "cancelled":
        return

    async def _run() -> None:
        try:
            await deliver_background_task_result(
                session=session,
                engine_pool=engine_pool,
                row=row,
                settings=settings,
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.error(
                "background_notify.failed",
                user_id=session.user_id,
                task_id=task_id,
                error=str(exc),
            )

    asyncio.create_task(_run(), name=f"bg-notify-{task_id[:8]}")


async def deliver_background_task_result(
    *,
    session: UserSession,
    engine_pool: EnginePool,
    row: TaskRow,
    settings: Settings,
) -> None:
    ws = session.websocket
    if ws is None or ws.client_state != WebSocketState.CONNECTED:
        return
    if session.interrupt.state.value in ("thinking", "speaking"):
        log.debug(
            "background_notify.deferred_busy",
            user_id=session.user_id,
            task_id=row.task_id,
        )
        session.pending_background_tasks.append(row.task_id)
        return

    from server.memory.warm import build_warm_profile
    from server.orchestrator.directives import strip_directives
    from server.orchestrator.prose import finalize_assistant_prose
    from server.orchestrator.supervisor import Supervisor
    from server.voice.captions import make_streaming_caption_handler
    from server.voice.streaming_tts import StreamingTtsPipeline, make_on_token_with_streaming_tts

    supervisor: Supervisor = session.supervisor
    history = await recent_turns(supervisor.session_id, limit=8)
    user_anchor = f"Background research finished: {row.goal}"

    turn_id = str(uuid.uuid4())
    session.interrupt.begin_thinking(turn_id)

    decision = compute_respond_via(
        capabilities_tts=session.capabilities.get("tts", True),
        client_state=session.client_control,
        input_kind="proactive",
    )

    voice = ws.app.state.voice
    pipeline: StreamingTtsPipeline | None = None
    if decision.respond_via == "voice_and_chat":
        pipeline = StreamingTtsPipeline(
            websocket=ws,
            turn_id=turn_id,
            interrupt=session.interrupt,
            tts=voice["tts"],
            emit_sentence_captions=True,
        )
        await pipeline.start()

    accumulated = ""

    def _acc(token: str) -> None:
        nonlocal accumulated
        accumulated += token

    on_token = make_on_token_with_streaming_tts(
        base_on_token=make_streaming_caption_handler(
            websocket=ws,
            turn_id=turn_id,
            interrupt=session.interrupt,
            accumulate=_acc,
            emit_partial_captions=pipeline is None,
        ),
        pipeline=pipeline,
    )

    warm = await build_warm_profile(supervisor.user_id)
    injected = format_background_done_block(row)
    raw = await supervisor._complete(
        user_text=user_anchor,
        warm_profile=warm,
        history=history,
        compressed_summary="",
        injected_context=injected,
        task_board_block=supervisor.task_board.render_for_main(),
        engine_pool=engine_pool,
        on_token=on_token,
        allow_delegates=False,
    )
    visible = finalize_assistant_prose(strip_directives(raw))
    if visible.strip():
        await append_turn(
            supervisor.session_id,
            supervisor.user_id,
            "assistant",
            visible,
        )

    delay = (
        settings.aec_client_suppression_delay_ms
        if session.capabilities.get("aec")
        else settings.self_echo_suppression_delay_ms
    )
    if pipeline is not None:
        await pipeline.flush()
        await pipeline.finish(delay)
    await deliver_turn_output(
        ws,
        turn_id=turn_id,
        assistant_text=visible,
        respond_via=decision.respond_via,
        interrupt=session.interrupt,
        tts=None,
        suppression_delay_ms=delay,
        stream_captions_during_llm=pipeline is not None,
        tts_streamed_during_llm=pipeline is not None,
    )
    session.interrupt.finish_turn()
    log.info(
        "background_notify.delivered",
        user_id=session.user_id,
        task_id=row.task_id,
        chars=len(visible),
    )


async def drain_pending_background_deliveries(
    session: UserSession,
    *,
    engine_pool: EnginePool,
    settings: Settings,
) -> None:
    pending = list(session.pending_background_tasks)
    session.pending_background_tasks.clear()
    for task_id in pending:
        row = session.supervisor.task_board.get(task_id)
        if row is None or row.status != "done":
            continue
        await deliver_background_task_result(
            session=session,
            engine_pool=engine_pool,
            row=row,
            settings=settings,
        )
