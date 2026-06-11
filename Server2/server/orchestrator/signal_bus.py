from __future__ import annotations

import json
from collections import deque
from collections.abc import Awaitable, Callable
from typing import Literal

from server.logger import get_logger
from server.memory.summarizer import schedule_task_fact_extraction
from server.orchestrator.task_board import TaskBoard, TaskRow
from server.subagents.report import ReportSignal

log = get_logger("orchestrator.signal_bus")

NOTIFIABLE_KINDS = frozenset({"DONE", "NEEDS_INFO", "ERROR"})

TaskEventKind = Literal["task_step", "task_done", "task_error"]
TaskEventEmitter = Callable[[TaskEventKind, str, str], Awaitable[None]]


def event_kind_for_report(kind: str) -> TaskEventKind:
    if kind == "DONE":
        return "task_done"
    if kind == "ERROR":
        return "task_error"
    return "task_step"


class SignalBus:
    """Sub-agent → Supervisor channel with optional Postgres audit."""

    def __init__(
        self,
        *,
        user_id: str,
        task_board: TaskBoard,
        on_event: TaskEventEmitter | None = None,
        persist: bool = True,
    ) -> None:
        self.user_id = user_id
        self.task_board = task_board
        self._on_event = on_event
        self._persist = persist
        self._pending: deque[ReportSignal] = deque()

    def set_event_emitter(self, emitter: TaskEventEmitter | None) -> None:
        self._on_event = emitter

    async def publish(self, signal: ReportSignal) -> TaskRow:
        row = self.task_board.upsert_from_signal(signal)
        self._pending.append(signal)
        if self._persist:
            await self._persist_signal(signal, row)
        if self._on_event is not None:
            kind = event_kind_for_report(signal.kind)
            await self._on_event(kind, signal.task_id, signal.summary)
        if signal.kind == "DONE":
            schedule_task_fact_extraction(
                task_id=signal.task_id,
                user_id=self.user_id,
                facts_payload=signal.payload.get("facts_to_persist"),
            )

        log.info(
            "signal_bus.published",
            user_id=self.user_id,
            task_id=signal.task_id,
            kind=signal.kind,
            status=row.status,
        )
        return row

    async def publish_task_created(
        self,
        *,
        task_id: str,
        capability: str,
        goal: str,
        payload: dict,
    ) -> TaskRow:
        existing = self.task_board.get(task_id)
        if existing is not None:
            return existing
        row = self.task_board.register_task(
            task_id=task_id,
            capability=capability,
            goal=goal,
            payload=payload,
        )
        if self._persist:
            await self._persist_task_row(row)
        if self._on_event is not None:
            await self._on_event("task_step", task_id, goal.strip()[:160])
        return row

    def drain(self) -> list[ReportSignal]:
        items = list(self._pending)
        self._pending.clear()
        return items

    def notifiable_pending(self) -> list[ReportSignal]:
        return [signal for signal in self._pending if signal.kind in NOTIFIABLE_KINDS]

    def drop_pending(self, signal: ReportSignal) -> None:
        try:
            self._pending.remove(signal)
        except ValueError:
            pass

    async def _persist_task_row(self, row: TaskRow) -> None:
        try:
            from server.db.postgres import get_pool

            pool = get_pool()
        except RuntimeError:
            return

        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO tasks (
                    task_id, user_id, capability, goal, status,
                    latest_step, payload, created_at, updated_at
                )
                VALUES ($1::uuid, $2, $3, $4, $5, $6, $7::jsonb, now(), now())
                ON CONFLICT (task_id) DO UPDATE SET
                    status = EXCLUDED.status,
                    latest_step = EXCLUDED.latest_step,
                    updated_at = now()
                """,
                row.task_id,
                self.user_id,
                row.capability,
                row.goal,
                row.status,
                row.latest_step,
                json.dumps(row.payload),
            )

    async def _persist_signal(self, signal: ReportSignal, row: TaskRow) -> None:
        try:
            from server.db.postgres import get_pool

            pool = get_pool()
        except RuntimeError:
            return

        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO signals (task_id, user_id, kind, summary, payload, importance)
                VALUES ($1::uuid, $2, $3, $4, $5::jsonb, $6)
                """,
                signal.task_id,
                self.user_id,
                signal.kind,
                signal.summary,
                json.dumps(signal.payload),
                signal.importance,
            )
            await conn.execute(
                """
                UPDATE tasks SET
                    status = $3,
                    latest_step = $4,
                    result_summary = $5,
                    waiting_for = $6,
                    blocked_reason = $7,
                    updated_at = now()
                WHERE task_id = $1::uuid AND user_id = $2
                """,
                signal.task_id,
                self.user_id,
                row.status,
                row.latest_step,
                row.result_summary,
                row.waiting_for,
                row.blocked_reason,
            )
