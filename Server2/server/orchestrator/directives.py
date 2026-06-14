from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Literal

from server.logger import get_logger
from server.memory import facts
from server.memory.retrieval import get_snippet_by_doc_id
from server.memory.warm import affects_warm_profile

log = get_logger("orchestrator.directives")

_RECALL_FOLLOWUP_HINT = (
    "Answer the user's latest message now in plain prose. "
    "If they asked for a story or explanation, provide it completely — "
    "do not ask them to choose again unless recall results are truly empty."
)

DirectiveKind = Literal[
    "remember",
    "recall",
    "recall_chain",
    "respond_via",
    "delegate",
    "answer_to",
    "stop_task",
]

RESPOND_VIA_RE = re.compile(
    r"\[RESPOND_VIA\s+(?P<mode>chat|voice|both)\s*\]",
    re.IGNORECASE,
)

REMEMBER_RE = re.compile(
    r'\[REMEMBER\s+key=(?P<key>[^\s\]]+)\s+value=(?P<value>.+?)\s+source=(?P<source>"[^"]+"|[^\s\]]+)\s*\]',
    re.IGNORECASE | re.DOTALL,
)
RECALL_DOC_RE = re.compile(
    r"\[RECALL\s+doc:(?P<doc_id>[^\s\]]+)\s*\]",
    re.IGNORECASE,
)
RECALL_CHAIN_RE = re.compile(
    r'\[RECALL\s+chain\s+key=(?P<key>[^\s\]]+)\s*\]',
    re.IGNORECASE,
)
RECALL_MEETING_RE = re.compile(
    r"\[RECALL\s+meeting:(?P<meeting_id>[^\s\]]+)\s*\]",
    re.IGNORECASE,
)
RECALL_RE = re.compile(
    r'\[RECALL\s+(?!chain\s|doc:|meeting:)key=(?P<key>[^\s\]]+)\s*\]',
    re.IGNORECASE,
)
DELEGATE_HEAD_RE = re.compile(
    r'\[DELEGATE\s+capability=(?P<capability>\w+)\s+goal="(?P<goal>[^"]*)"\s+payload=',
    re.IGNORECASE,
)
ANSWER_TO_RE = re.compile(
    r'\[ANSWER_TO\s+task_id=(?P<task_id>[^\s]+)\s+answer="(?P<answer>[^"]*)"\s+mode=(?P<mode>reply|amendment)\s*\]',
    re.IGNORECASE,
)
STOP_TASK_RE = re.compile(
    r"\[STOP_TASK\s+task_id=(?P<task_id>[^\s]+)\s*\]",
    re.IGNORECASE,
)
DIRECTIVE_BLOCK_RE = re.compile(
    r'\[(?:REMEMBER|RECALL|RESPOND_VIA|DELEGATE|ANSWER_TO|STOP_TASK)(?:\s+chain)?\s+[^\]]+\]',
    re.IGNORECASE,
)


@dataclass(frozen=True)
class RememberDirective:
    key: str
    value: Any
    source: str


@dataclass(frozen=True)
class RecallDirective:
    key: str
    chain: bool = False


@dataclass(frozen=True)
class RecallDocDirective:
    doc_id: str


@dataclass(frozen=True)
class RecallMeetingDirective:
    meeting_id: str


@dataclass(frozen=True)
class RecallResult:
    key: str
    chain: bool
    payload: str
    doc_id: str | None = None


@dataclass(frozen=True)
class DelegateDirective:
    capability: str
    goal: str
    payload: dict[str, Any]


@dataclass(frozen=True)
class AnswerToDirective:
    task_id: str
    answer: str
    mode: Literal["reply", "amendment"] = "reply"


@dataclass(frozen=True)
class StopTaskDirective:
    task_id: str


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


def parse_answer_to_directives(text: str) -> list[AnswerToDirective]:
    return [
        AnswerToDirective(
            task_id=match.group("task_id"),
            answer=match.group("answer"),
            mode=match.group("mode").lower(),  # type: ignore[arg-type]
        )
        for match in ANSWER_TO_RE.finditer(text)
    ]


def parse_stop_task_directives(text: str) -> list[StopTaskDirective]:
    return [
        StopTaskDirective(task_id=match.group("task_id"))
        for match in STOP_TASK_RE.finditer(text)
    ]


def parse_delegate_directives(text: str) -> list[DelegateDirective]:
    found: list[DelegateDirective] = []
    for match in DELEGATE_HEAD_RE.finditer(text):
        payload_raw = _extract_json_object(text, match.end())
        if payload_raw is None:
            continue
        try:
            payload = json.loads(payload_raw)
        except json.JSONDecodeError:
            log.warning("directives.delegate_invalid_json", goal=match.group("goal"))
            continue
        if not isinstance(payload, dict):
            continue
        found.append(
            DelegateDirective(
                capability=match.group("capability"),
                goal=match.group("goal"),
                payload=payload,
            )
        )
    return found


ProfileDirective = (
    RememberDirective | RecallDirective | RecallDocDirective | RecallMeetingDirective
)


def parse_directives(text: str) -> list[ProfileDirective]:
    found: list[ProfileDirective] = []
    for match in RECALL_DOC_RE.finditer(text):
        found.append(RecallDocDirective(doc_id=match.group("doc_id")))
    for match in RECALL_MEETING_RE.finditer(text):
        found.append(RecallMeetingDirective(meeting_id=match.group("meeting_id")))
    for match in RECALL_CHAIN_RE.finditer(text):
        found.append(RecallDirective(key=match.group("key"), chain=True))
    for match in RECALL_RE.finditer(text):
        found.append(RecallDirective(key=match.group("key"), chain=False))
    for match in REMEMBER_RE.finditer(text):
        raw_value = match.group("value").strip()
        if raw_value.startswith('"') and raw_value.endswith('"'):
            value: Any = json.loads(raw_value)
        else:
            try:
                value = json.loads(raw_value)
            except json.JSONDecodeError:
                value = raw_value
        source = match.group("source").strip().strip('"')
        found.append(
            RememberDirective(
                key=match.group("key"),
                value=value,
                source=source,
            )
        )
    return found


def parse_respond_via_override(text: str) -> Literal["chat", "voice", "both"] | None:
    match = RESPOND_VIA_RE.search(text)
    if not match:
        return None
    mode = match.group("mode").lower()
    if mode in ("chat", "voice", "both"):
        return mode  # type: ignore[return-value]
    return None


def filter_profile_directives(
    directives: list[ProfileDirective],
) -> list[ProfileDirective]:
    """Drop REMEMBER/RECALL for keys outside the profile namespace."""
    kept: list[ProfileDirective] = []
    for directive in directives:
        if isinstance(directive, (RecallDocDirective, RecallMeetingDirective)):
            kept.append(directive)
            continue
        if not affects_warm_profile(directive.key):
            log.debug("directives.skipped_non_profile_key", key=directive.key)
            continue
        kept.append(directive)
    return kept


TOOL_SEARCH_META_RE = re.compile(
    r"^Found \d+ tool\(s\) for .+$",
    re.IGNORECASE,
)
INTERNAL_MARKER_RE = re.compile(
    r"\[(?:SUBAGENT_SPAWN|BACKGROUND_TASK_DONE|PROACTIVE_SIGNAL)\b[^\]]*\]"
    r"(?:\s*\([^\n]*\))?",
    re.IGNORECASE,
)
TRANSCRIPT_LABEL_RE = re.compile(
    r"^(?P<label>User|Vayumi|Assistant|Worker):\s*",
    re.IGNORECASE,
)


def strip_internal_tool_blocks(text: str) -> str:
    """Remove injected tool traces — never user-visible."""
    text = INTERNAL_MARKER_RE.sub("", text)
    kept: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("[TOOL_RESULT"):
            continue
        label_match = TRANSCRIPT_LABEL_RE.match(stripped)
        if label_match:
            if label_match.group("label").lower() in ("user", "worker"):
                continue
            remainder = TRANSCRIPT_LABEL_RE.sub("", stripped).strip()
            if not remainder:
                continue
            stripped = remainder
        if TOOL_SEARCH_META_RE.match(stripped):
            continue
        if re.search(r"\d+\s+result\(s\)\s+from\s+tavily", stripped, re.IGNORECASE):
            continue
        if re.match(r"^\d+\.\s+.+\s+—\s+", stripped):
            continue
        if stripped.startswith("=== ") or stripped.startswith("--- Immediate result"):
            continue
        if stripped in ("Here's a summary of the results:", "Here's a summary:"):
            continue
        kept.append(stripped)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(kept)).strip()


def plan_acknowledgment(text: str) -> str:
    """
    Spoken line(s) from the model's plan turn — prose before any [DELEGATE] / tool block.
    Used as live status while tools run (not a template).
    """
    if not text.strip():
        return ""
    earliest = len(text)
    for pattern in (
        DELEGATE_HEAD_RE,
        REMEMBER_RE,
        RECALL_DOC_RE,
        RECALL_MEETING_RE,
        RECALL_CHAIN_RE,
        RECALL_RE,
        ANSWER_TO_RE,
        STOP_TASK_RE,
        RESPOND_VIA_RE,
    ):
        match = pattern.search(text)
        if match:
            earliest = min(earliest, match.start())
    head = text[:earliest].strip() if earliest < len(text) else text.strip()
    head = strip_internal_tool_blocks(strip_directives(head))
    head = re.sub(r"[\s\[\]!]+$", "", head).strip()
    if not head:
        return ""
    if len(head) > 300:
        head = head[:297].rsplit(" ", 1)[0] + "…"
    return head


def strip_directives(text: str) -> str:
    cleaned = text
    for match in DELEGATE_HEAD_RE.finditer(text):
        payload_raw = _extract_json_object(text, match.end())
        if payload_raw is not None:
            block = text[match.start() : match.end() + len(payload_raw)]
            cleaned = cleaned.replace(block, "", 1)
    cleaned = ANSWER_TO_RE.sub("", cleaned)
    cleaned = STOP_TASK_RE.sub("", cleaned)
    cleaned = INTERNAL_MARKER_RE.sub("", cleaned)
    cleaned = DIRECTIVE_BLOCK_RE.sub("", cleaned)
    cleaned = RESPOND_VIA_RE.sub("", cleaned)
    cleaned = strip_internal_tool_blocks(cleaned)
    cleaned = re.sub(r"^\s*[\]\[!]+\s*$", "", cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r"^\s*\]\s*", "", cleaned)
    # Remove lines with partial or complete [DELEGATE blocks
    kept: list[str] = []
    for line in cleaned.splitlines():
        if re.search(r"\[DELEGATE\b", line, re.IGNORECASE):
            continue
        kept.append(line)
    cleaned = "\n".join(kept)
    # Strip trailing incomplete [DELEGATE ... (no closing ])
    cleaned = re.sub(
        r"\[DELEGATE\b[^\]]*$", "", cleaned, flags=re.IGNORECASE | re.DOTALL
    )
    return re.sub(r"\n{3,}", "\n\n", cleaned).strip()


_DIRECTIVE_LEAK_RE = re.compile(
    r"\[DELEGATE\b|(?:^|\s)capability=\w+.*goal=|payload=\{",
    re.IGNORECASE,
)


def contains_directive_leak(text: str) -> bool:
    """True when model output still contains internal directive syntax."""
    return bool(_DIRECTIVE_LEAK_RE.search(text.strip()))


async def execute_directives(
    user_id: str,
    directives: list[ProfileDirective],
) -> list[RecallResult]:
    results: list[RecallResult] = []
    for directive in directives:
        if isinstance(directive, RememberDirective):
            await facts.set_fact(
                user_id,
                directive.key,
                directive.value,
                directive.source,
            )
            continue

        if isinstance(directive, RecallMeetingDirective):
            from server.memory.retrieval import get_meeting_recall

            payload = await get_meeting_recall(
                user_id,
                directive.meeting_id,
            )
            results.append(
                RecallResult(
                    key=f"meeting:{directive.meeting_id}:summary",
                    chain=False,
                    payload=payload,
                )
            )
            log.info(
                "directives.recall_meeting",
                user_id=user_id,
                meeting_id=directive.meeting_id,
            )
            continue

        if isinstance(directive, RecallDocDirective):
            snippet = await get_snippet_by_doc_id(user_id, directive.doc_id)
            if snippet is None:
                payload = f"(no document for doc_id={directive.doc_id})"
            else:
                payload = f"{snippet.text} ({snippet.citation})"
            results.append(
                RecallResult(
                    key=snippet.key if snippet is not None else "",
                    chain=False,
                    payload=payload,
                    doc_id=directive.doc_id,
                )
            )
            log.info(
                "directives.recall_doc",
                user_id=user_id,
                doc_id=directive.doc_id,
                hit=snippet is not None,
            )
            continue

        if directive.chain:
            chain = await facts.get_chain(user_id, directive.key)
            if not chain:
                payload = f"(no history for key={directive.key})"
            else:
                parts = []
                for row in chain:
                    status = "active" if row.active else "superseded"
                    parts.append(
                        f"{status}: {json.dumps(row.value)} (since {row.created_at.isoformat()})"
                    )
                payload = "; ".join(parts)
        else:
            record = await facts.get_fact(user_id, directive.key)
            payload = (
                json.dumps(record.value)
                if record is not None
                else f"(no active fact for key={directive.key})"
            )

        results.append(
            RecallResult(
                key=directive.key,
                chain=directive.chain,
                payload=payload,
            )
        )
        log.info(
            "directives.recall",
            user_id=user_id,
            key=directive.key,
            chain=directive.chain,
        )
    return results


def format_recall_results(results: list[RecallResult]) -> str:
    if not results:
        return ""
    lines = []
    for item in results:
        if item.doc_id:
            lines.append(f"[RECALL_RESULT doc={item.doc_id}] {item.payload}")
            continue
        label = "chain" if item.chain else "key"
        lines.append(f"[RECALL_RESULT {label}={item.key}] {item.payload}")
    block = "\n".join(lines)
    return f"{block}\n\n{_RECALL_FOLLOWUP_HINT}"
