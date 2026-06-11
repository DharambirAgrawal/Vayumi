from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Literal

from server.subagents.report import ReportSignal

TaskStatus = Literal[
    "running",
    "paused",
    "blocked",
    "waiting_user",
    "done",
    "error",
    "cancelled",
]

TERMINAL_STATUSES = frozenset({"done", "error", "cancelled"})


@dataclass
class TaskRow:
    task_id: str
    capability: str
    goal: str
    status: TaskStatus = "running"
    latest_step: str | None = None
    result_summary: str | None = None
    blocked_reason: str | None = None
    waiting_for: str | None = None
    note_for_agent: str | None = None
    suggestion: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)

    def to_active_dict(self) -> dict[str, Any]:
        allowed = ["answer", "cancel"]
        if self.status == "running":
            allowed.append("amendment")
        return {
            "task_id": self.task_id,
            "capability": self.capability,
            "goal": self.goal,
            "status": self.status,
            "latest_step": self.latest_step,
            "waiting_for": self.waiting_for,
            "result_summary": self.result_summary,
            "allowed_actions": allowed,
        }

    def to_completed_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "status": self.status,
            "result_summary": self.result_summary,
            "note_for_agent": self.note_for_agent,
            "suggestion": self.suggestion,
        }


class TaskBoard:
    """Per-user canonical task state for Main context and client snapshots."""

    def __init__(
        self,
        user_id: str,
        *,
        max_active: int = 8,
        max_completed: int = 5,
    ) -> None:
        self.user_id = user_id
        self.max_active = max_active
        self.max_completed = max_completed
        self._active: dict[str, TaskRow] = {}
        self._completed: list[TaskRow] = []

    def register_task(
        self,
        *,
        task_id: str,
        capability: str,
        goal: str,
        payload: dict[str, Any] | None = None,
    ) -> TaskRow:
        row = TaskRow(
            task_id=task_id,
            capability=capability,
            goal=goal,
            status="running",
            payload=payload or {},
        )
        self._active[task_id] = row
        self._trim_active()
        return row

    def get(self, task_id: str) -> TaskRow | None:
        if task_id in self._active:
            return self._active[task_id]
        for row in self._completed:
            if row.task_id == task_id:
                return row
        return None

    def upsert_from_signal(self, signal: ReportSignal) -> TaskRow:
        row = self._active.get(signal.task_id)
        if row is None:
            row = TaskRow(
                task_id=signal.task_id,
                capability="unknown",
                goal=signal.summary,
            )
            self._active[signal.task_id] = row

        if signal.kind == "STEP":
            row.status = "running"
            row.latest_step = signal.summary
            row.waiting_for = None
        elif signal.kind == "NEEDS_INFO":
            row.status = "paused"
            row.latest_step = signal.summary
            question = signal.payload.get("question")
            row.waiting_for = question if isinstance(question, str) else signal.summary
            row.blocked_reason = signal.payload.get("reason")
        elif signal.kind == "DONE":
            row.status = "done"
            row.result_summary = signal.summary
            row.latest_step = signal.summary
            row.waiting_for = None
            note = signal.payload.get("note_for_agent")
            if isinstance(note, str):
                row.note_for_agent = note
            suggestion = signal.payload.get("suggestion")
            if isinstance(suggestion, str):
                row.suggestion = suggestion
            self._finalize(row)
        elif signal.kind == "ERROR":
            row.status = "error"
            row.result_summary = signal.summary
            row.blocked_reason = signal.payload.get("reason")
            if signal.payload.get("user_actionable"):
                row.status = "waiting_user"
                row.waiting_for = signal.summary
            self._finalize(row)

        return row

    def mark_cancelled(self, task_id: str, *, summary: str = "cancelled") -> TaskRow | None:
        row = self._active.get(task_id)
        if row is None:
            return None
        row.status = "cancelled"
        row.result_summary = summary
        self._finalize(row)
        return row

    def find_running(self, capability: str, goal: str) -> TaskRow | None:
        """Avoid duplicate background workers for the same goal."""
        cap = capability.lower()
        needle = goal.strip().lower()[:80]
        if not needle:
            return None
        for row in self._active.values():
            if row.status in TERMINAL_STATUSES:
                continue
            if row.capability.lower() != cap:
                continue
            if row.goal.strip().lower()[:80] == needle:
                return row
        return None

    def format_completed_injection(self, user_text: str = "") -> str:
        """
        Inject finished background work relevant to the user's message.
        Avoids dumping unrelated completed tasks (e.g. quantum) when they ask about SpaceX.
        """
        rows = list(self._completed[: self.max_completed])
        lower = user_text.strip().lower()
        continue_short = (
            rows
            and len(lower) < 48
            and any(
                phrase in lower
                for phrase in ("continue", "go on", "keep going", "tell me more", "yes")
            )
        )
        if continue_short:
            rows = [rows[0]]

        keywords = set() if continue_short else _topic_keywords(user_text)
        if keywords:
            matched = [
                row
                for row in rows
                if any(token in row.goal.lower() for token in keywords)
            ]
            if matched:
                rows = matched
            else:
                rows = []

        blocks: list[str] = []
        for row in rows:
            summary = (row.result_summary or "").strip()
            if not summary:
                continue
            blocks.append(
                f'[BACKGROUND_TASK_DONE task_id={row.task_id} capability={row.capability} '
                f'goal="{row.goal}"]\n{summary}'
            )
        if not blocks:
            if keywords and user_text.strip():
                return (
                    "=== Background research status ===\n"
                    "No completed background task matches the user's latest question. "
                    "If they asked for deep research on a new topic, check active_tasks — "
                    "if none, say you have not started that deep job yet (do not recycle "
                    "older quantum/Nepal/weather results)."
                )
            return ""
        return (
            "=== Background research finished (answer the user from this now) ===\n"
            + "\n\n".join(blocks)
            + "\n\nSummarize ONLY these findings in spoken prose. No URLs. Do not start "
            "another research DELEGATE for the same topic."
        )

    def render_for_main(self) -> str:
        active = [
            row.to_active_dict()
            for row in self._active.values()
            if row.status not in TERMINAL_STATUSES
        ][: self.max_active]
        completed = [row.to_completed_dict() for row in self._completed[: self.max_completed]]
        if not active and not completed:
            return ""
        block = {
            "active_tasks": active,
            "recent_completed": completed,
        }
        hint = (
            "If recent_completed has entries and the user follows up, summarize those results. "
            "If active_tasks shows running for the same goal, do not spawn duplicate research — "
            "say it is still running or use completed results."
        )
        return (
            f"{hint}\n"
            "Active background tasks (structured — paraphrase for the user when asked):\n"
            + json.dumps(block, ensure_ascii=False)
        )

    def snapshot(self) -> dict[str, object]:
        active = list(self._active.values())
        running = sum(1 for r in active if r.status == "running")
        paused = sum(1 for r in active if r.status in ("paused", "waiting_user"))
        return {
            "active_tasks": [
                row.to_active_dict()
                for row in active
                if row.status not in TERMINAL_STATUSES
            ],
            "recent_completed": [row.to_completed_dict() for row in self._completed],
            "running": running,
            "paused": paused,
        }

    def _finalize(self, row: TaskRow) -> None:
        self._active.pop(row.task_id, None)
        self._completed.insert(0, row)
        if len(self._completed) > self.max_completed:
            self._completed = self._completed[: self.max_completed]

    def _trim_active(self) -> None:
        if len(self._active) <= self.max_active:
            return
        excess = len(self._active) - self.max_active
        for task_id in list(self._active.keys())[:excess]:
            row = self._active.pop(task_id)
            row.status = "error"
            row.result_summary = "dropped (task board limit)"
            self._completed.insert(0, row)


def _topic_keywords(user_text: str) -> set[str]:
    """Tokens from the user message used to match completed task goals."""
    stop = {
        "what",
        "did",
        "you",
        "find",
        "tell",
        "about",
        "latest",
        "news",
        "today",
        "read",
        "full",
        "sources",
        "research",
        "deep",
        "start",
        "also",
        "with",
        "the",
        "and",
        "for",
        "from",
        "that",
        "this",
        "have",
        "when",
        "your",
        "more",
        "going",
        "happening",
        "weather",
        "stock",
    }
    tokens: set[str] = set()
    for word in re.findall(r"[a-z0-9]{4,}", user_text.lower()):
        if word not in stop:
            tokens.add(word)
    return tokens
