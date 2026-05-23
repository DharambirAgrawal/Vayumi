from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from server.logger import get_logger

log = get_logger("subagents.report")

ReportKind = Literal["STEP", "NEEDS_INFO", "DONE", "ERROR"]

REPORT_HEAD_RE = re.compile(
    r'\[REPORT\s+kind=(?P<kind>STEP|NEEDS_INFO|DONE|ERROR)\s+summary="(?P<summary>[^"]*)"\s+payload=',
    re.IGNORECASE,
)


class ReportSignal(BaseModel):
    task_id: str
    kind: ReportKind
    summary: str
    payload: dict[str, Any] = Field(default_factory=dict)
    importance: float = 0.5
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @model_validator(mode="after")
    def _needs_info_importance(self) -> ReportSignal:
        if self.kind == "NEEDS_INFO" and self.importance < 1.0:
            self.importance = 1.0
        return self


def report(
    task_id: str,
    kind: ReportKind,
    summary: str,
    payload: dict[str, Any] | None = None,
    *,
    importance: float = 0.5,
) -> ReportSignal:
    """Build a validated report signal (sub-agent output contract)."""
    return ReportSignal(
        task_id=task_id,
        kind=kind,
        summary=summary.strip(),
        payload=payload or {},
        importance=importance,
    )


def _extract_json_object(text: str, start: int) -> str | None:
    if start >= len(text) or text[start] != "{":
        return None
    depth = 0
    in_string = False
    escape = False
    for idx in range(start, len(text)):
        ch = text[idx]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : idx + 1]
    return None


def parse_report_directives(text: str, *, task_id: str) -> list[ReportSignal]:
    """Parse [REPORT kind=... summary="..." payload={...}] blocks from model text."""
    found: list[ReportSignal] = []
    for match in REPORT_HEAD_RE.finditer(text):
        payload_raw = _extract_json_object(text, match.end())
        if payload_raw is None:
            continue
        try:
            payload = json.loads(payload_raw)
        except json.JSONDecodeError:
            log.warning("report.invalid_json", task_id=task_id)
            continue
        if not isinstance(payload, dict):
            payload = {}
        kind = match.group("kind").upper()
        try:
            signal = ReportSignal(
                task_id=task_id,
                kind=kind,  # type: ignore[arg-type]
                summary=match.group("summary"),
                payload=payload,
            )
        except Exception as exc:
            log.warning("report.validation_failed", task_id=task_id, error=str(exc))
            continue
        found.append(signal)
    return found


def format_report_directive(signal: ReportSignal) -> str:
    payload_json = json.dumps(signal.payload, ensure_ascii=False)
    return (
        f'[REPORT kind={signal.kind} summary="{signal.summary}" payload={payload_json}]'
    )
