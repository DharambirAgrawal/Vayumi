from __future__ import annotations

import asyncio
import time
import uuid
from typing import TYPE_CHECKING

from starlette.websockets import WebSocket, WebSocketState

from server.logger import get_logger
from server.orchestrator.signal_bus import NOTIFIABLE_KINDS
from server.orchestrator.task_board import TaskRow
from server.subagents.report import ReportSignal
from server.transport.outbound import send_json
from server.transport.protocol import NotificationMessage, NotificationPayload
from server.transport.session_registry import UserSession, iter_user_sessions
from server.transport.turn_coordinator import run_supervisor_text_turn, session_busy
from server.voice.respond_via import RespondViaDecision, compute_respond_via

if TYPE_CHECKING:
    from server.config import Settings
    from server.engine.pool import EnginePool

log = get_logger("orchestrator.notifier")


def signal_surface_key(signal: ReportSignal) -> str:
    return f"{signal.task_id}:{signal.kind}:{int(signal.created_at.timestamp() * 1000)}"


def user_is_idle(session: UserSession) -> bool:
    if session.notifier_inflight:
        return False
    if session.turn_task is not None and not session.turn_task.done():
        return False
    if session.queued_chat_text:
        return False
    if session_busy(session):
        return False
    return True


def maybe_surface_signal(
    signal: ReportSignal,
    session: UserSession,
    *,
    settings: Settings,
    now: float | None = None,
) -> bool:
    """Gate proactive surfacing by silence, importance, debounce, and client state."""
    if signal.kind not in NOTIFIABLE_KINDS:
        return False

    key = signal_surface_key(signal)
    if key in session.surfaced_signal_keys:
        return False

    if not user_is_idle(session):
        return False

    if signal.importance < settings.notifier_importance_threshold:
        return False

    ts = now if now is not None else time.monotonic()
    if signal.kind != "NEEDS_INFO" and session.last_proactive_at is not None:
        elapsed = ts - session.last_proactive_at
        if elapsed < settings.notifier_min_interval_seconds:
            return False

    return True


def format_synthetic_user_text(signal: ReportSignal, row: TaskRow | None) -> str:
    if signal.kind == "NEEDS_INFO":
        question = None
        if row is not None and row.waiting_for:
            question = row.waiting_for
        if question is None:
            question = signal.payload.get("question")
        if not isinstance(question, str) or not question.strip():
            question = signal.summary
        return (
            "Background task needs user input. Ask the user naturally in one voice."
        )

    if signal.kind == "ERROR":
        return (
            "Background task failed and may need user action. Explain the blocker briefly."
        )

    return (
        "Background task finished while the user was silent. "
        "Tell the user briefly what is ready."
    )


def format_proactive_injection(signal: ReportSignal, row: TaskRow | None) -> str:
    goal = row.goal if row is not None else signal.summary
    summary = (row.result_summary if row is not None else None) or signal.summary
    waiting = row.waiting_for if row is not None else None
    capability = row.capability if row is not None else "unknown"

    lines = [
        f"[PROACTIVE_SIGNAL kind={signal.kind} task_id={signal.task_id} "
        f'capability={capability} goal="{goal}"]',
        summary.strip(),
    ]
    if waiting:
        lines.append(f"waiting_for: {waiting.strip()}")
    if signal.payload.get("question") and isinstance(signal.payload["question"], str):
        lines.append(f"question: {signal.payload['question'].strip()}")
    lines.append(
        "Speak as Main in one short voice. Use structured fields only — no raw tool traces. "
        "Do not emit [DELEGATE], [REMEMBER], or [RECALL]."
    )
    return "\n".join(line for line in lines if line)


def pick_next_signal(signals: list[ReportSignal]) -> ReportSignal | None:
    if not signals:
        return None
    ranked = sorted(
        signals,
        key=lambda signal: (
            0 if signal.kind == "NEEDS_INFO" else 1,
            -signal.importance,
            signal.created_at,
        ),
    )
    return ranked[0]


async def send_notification_toast(
    websocket: WebSocket,
    *,
    task_id: str,
    text: str,
) -> None:
    preview = text.strip()
    if len(preview) > 160:
        preview = preview[:157] + "..."
    if not preview:
        return
    await send_json(
        websocket,
        NotificationMessage(
            payload=NotificationPayload(task_id=task_id, text=preview),
        ),
    )


async def build_synthetic_turn(
    signals: list[ReportSignal],
    session: UserSession,
    *,
    engine_pool: EnginePool,
    settings: Settings,
) -> None:
    """Run Main through the normal delivery path for a proactive synthetic turn."""
    websocket = session.websocket
    if websocket is None or websocket.client_state != WebSocketState.CONNECTED:
        return

    signal = pick_next_signal(signals)
    if signal is None:
        return

    row = session.supervisor.task_board.get(signal.task_id)
    decision: RespondViaDecision = compute_respond_via(
        capabilities_tts=session.capabilities.get("tts", True),
        client_state=session.client_control,
        input_kind="proactive",
    )

    user_text = format_synthetic_user_text(signal, row)
    injected = format_proactive_injection(signal, row)
    preview = (row.waiting_for if row and row.waiting_for else None) or signal.summary

    if decision.respond_via == "chat_only" and not session.client_control.visible:
        await send_notification_toast(
            websocket,
            task_id=signal.task_id,
            text=preview,
        )

    turn_id = str(uuid.uuid4())
    session.notifier_inflight = True

    try:
        await run_supervisor_text_turn(
            websocket,
            session,
            user_text,
            settings,
            engine_pool,
            input_kind="proactive",
            computed_respond_via=decision.respond_via,
            turn_id=turn_id,
            allow_delegates=False,
            injected_context=injected,
            interrupt_policy=decision.interrupt_policy,
        )
        session.surfaced_signal_keys.add(signal_surface_key(signal))
        session.last_proactive_at = time.monotonic()
        session.supervisor.signal_bus.drop_pending(signal)
        log.info(
            "notifier.synthetic_turn_complete",
            user_id=session.user_id,
            task_id=signal.task_id,
            kind=signal.kind,
            respond_via=decision.respond_via,
        )
    finally:
        session.notifier_inflight = False


class ProactiveNotifier:
    """Background loop: surface sub-agent DONE/NEEDS_INFO/ERROR when user is idle."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()

    def start(self, app) -> None:
        if self._task is not None and not self._task.done():
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._run_loop(app), name="proactive-notifier")
        log.info(
            "notifier.started",
            tick_seconds=self._settings.notifier_tick_seconds,
        )

    async def stop(self) -> None:
        self._stop.set()
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None
        log.info("notifier.stopped")

    async def _run_loop(self, app) -> None:
        while not self._stop.is_set():
            try:
                await self._tick(app)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.error("notifier.tick_failed", error=str(exc))
            try:
                await asyncio.wait_for(
                    self._stop.wait(),
                    timeout=self._settings.notifier_tick_seconds,
                )
                break
            except TimeoutError:
                continue

    async def _tick(self, app) -> None:
        engine_pool: EnginePool = app.state.engine_pool
        for session in iter_user_sessions():
            await self._tick_session(session, engine_pool)

    async def _tick_session(self, session: UserSession, engine_pool: EnginePool) -> None:
        websocket = session.websocket
        if websocket is None or websocket.client_state != WebSocketState.CONNECTED:
            return

        pending = session.supervisor.signal_bus.notifiable_pending()
        if not pending:
            return

        now = time.monotonic()
        for signal in sorted(
            pending,
            key=lambda item: (
                0 if item.kind == "NEEDS_INFO" else 1,
                -item.importance,
                item.created_at,
            ),
        ):
            if not maybe_surface_signal(signal, session, settings=self._settings, now=now):
                continue
            await build_synthetic_turn(
                [signal],
                session,
                engine_pool=engine_pool,
                settings=self._settings,
            )
            break


_notifier: ProactiveNotifier | None = None


def start_notifier(app) -> None:
    global _notifier
    settings: Settings = app.state.settings
    _notifier = ProactiveNotifier(settings)
    _notifier.start(app)


async def stop_notifier() -> None:
    global _notifier
    if _notifier is None:
        return
    await _notifier.stop()
    _notifier = None
