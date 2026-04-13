from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional

from .worker_base import LiteRTWorker


@dataclass
class TaskSession:
    task_id: str
    description: str
    capability: str
    status: str
    tool_ids: list[str]
    worker: LiteRTWorker
    pending_question: Optional[str]
    step_log: list[str]
    last_step_message: str
    created_at: float
    step_count: int
    max_steps: int
    timeout_at: float


class SessionStore:
    def __init__(self):
        self._tasks: dict[str, dict[str, TaskSession]] = {}

    def add(self, speaker_id: str, task: TaskSession) -> None:
        self._tasks.setdefault(speaker_id, {})[task.task_id] = task

    def get(self, speaker_id: str, task_id: str) -> Optional[TaskSession]:
        return self._tasks.get(speaker_id, {}).get(task_id)

    def mark_paused(self, speaker_id: str, task_id: str, question: str) -> None:
        task = self.get(speaker_id, task_id)
        if not task:
            return
        task.status = "paused"
        task.pending_question = question

    def mark_closed(self, speaker_id: str, task_id: str, status: str = "done") -> None:
        task = self.get(speaker_id, task_id)
        if not task:
            return
        task.status = status

    def update_step(self, speaker_id: str, task_id: str, message: str) -> None:
        task = self.get(speaker_id, task_id)
        if not task:
            return
        task.last_step_message = message
        task.step_count += 1

    def stop_and_remove(self, speaker_id: str, task_id: str) -> None:
        task = self.get(speaker_id, task_id)
        if task:
            task.worker.stop()
        self._tasks.get(speaker_id, {}).pop(task_id, None)

    def stop_all(self, speaker_id: str) -> None:
        tasks = self._tasks.get(speaker_id, {})
        for task_id in list(tasks):
            self.stop_and_remove(speaker_id, task_id)

    def get_active_tasks_block(self, speaker_id: str) -> str:
        tasks = self._tasks.get(speaker_id, {})
        if not tasks:
            return ""

        lines = ["[ACTIVE TASKS]"]
        for task in tasks.values():
            if task.status == "running":
                suffix = f" (last: {task.last_step_message})" if task.last_step_message else ""
                lines.append(f'{task.task_id}: "{task.description}" - running{suffix}')
            elif task.status == "paused":
                lines.append(
                    f'{task.task_id}: "{task.description}" - paused, waiting for: "{task.pending_question or "input"}"'
                )
            elif task.status == "done":
                lines.append(f'{task.task_id}: "{task.description}" - done')
            elif task.status == "error":
                lines.append(f'{task.task_id}: "{task.description}" - error')
        return "\n".join(lines)

    def expire_timeouts(self, speaker_id: str) -> list[str]:
        now = time.time()
        expired: list[str] = []
        for task_id, task in list(self._tasks.get(speaker_id, {}).items()):
            if task.timeout_at <= now:
                expired.append(task_id)
        return expired


session_store = SessionStore()
