from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Literal

from server.logger import get_logger
from server.memory import facts
from server.memory.warm import affects_warm_profile

log = get_logger("orchestrator.directives")

_RECALL_FOLLOWUP_HINT = (
    "Answer the user's latest message now in plain prose. "
    "If they asked for a story or explanation, provide it completely — "
    "do not ask them to choose again unless recall results are truly empty."
)

DirectiveKind = Literal["remember", "recall", "recall_chain", "respond_via", "delegate"]

RESPOND_VIA_RE = re.compile(
    r"\[RESPOND_VIA\s+(?P<mode>chat|voice|both)\s*\]",
    re.IGNORECASE,
)

REMEMBER_RE = re.compile(
    r'\[REMEMBER\s+key=(?P<key>[^\s\]]+)\s+value=(?P<value>.+?)\s+source=(?P<source>"[^"]+"|[^\s\]]+)\s*\]',
    re.IGNORECASE | re.DOTALL,
)
RECALL_CHAIN_RE = re.compile(
    r'\[RECALL\s+chain\s+key=(?P<key>[^\s\]]+)\s*\]',
    re.IGNORECASE,
)
RECALL_RE = re.compile(
    r'\[RECALL\s+(?!chain\s)key=(?P<key>[^\s\]]+)\s*\]',
    re.IGNORECASE,
)
DELEGATE_HEAD_RE = re.compile(
    r'\[DELEGATE\s+capability=(?P<capability>\w+)\s+goal="(?P<goal>[^"]*)"\s+payload=',
    re.IGNORECASE,
)
DIRECTIVE_BLOCK_RE = re.compile(
    r'\[(?:REMEMBER|RECALL|RESPOND_VIA|DELEGATE)(?:\s+chain)?\s+[^\]]+\]',
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
class RecallResult:
    key: str
    chain: bool
    payload: str


@dataclass(frozen=True)
class DelegateDirective:
    capability: str
    goal: str
    payload: dict[str, Any]


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


def parse_directives(text: str) -> list[RememberDirective | RecallDirective]:
    found: list[RememberDirective | RecallDirective] = []
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
    directives: list[RememberDirective | RecallDirective],
) -> list[RememberDirective | RecallDirective]:
    """Drop REMEMBER/RECALL for keys outside the profile namespace."""
    kept: list[RememberDirective | RecallDirective] = []
    for directive in directives:
        if not affects_warm_profile(directive.key):
            log.debug("directives.skipped_non_profile_key", key=directive.key)
            continue
        kept.append(directive)
    return kept


TOOL_SEARCH_META_RE = re.compile(
    r"^Found \d+ tool\(s\) for .+$",
    re.IGNORECASE,
)


def strip_internal_tool_blocks(text: str) -> str:
    """Remove injected tool traces — never user-visible."""
    kept: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("[TOOL_RESULT"):
            continue
        if TOOL_SEARCH_META_RE.match(stripped):
            continue
        if stripped in ("Here's a summary of the results:", "Here's a summary:"):
            continue
        kept.append(line)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(kept)).strip()


def strip_directives(text: str) -> str:
    cleaned = text
    for match in DELEGATE_HEAD_RE.finditer(text):
        payload_raw = _extract_json_object(text, match.end())
        if payload_raw is not None:
            block = text[match.start() : match.end() + len(payload_raw)]
            cleaned = cleaned.replace(block, "", 1)
    cleaned = DIRECTIVE_BLOCK_RE.sub("", cleaned)
    cleaned = RESPOND_VIA_RE.sub("", cleaned)
    cleaned = strip_internal_tool_blocks(cleaned)
    return re.sub(r"\n{3,}", "\n\n", cleaned).strip()


async def execute_directives(
    user_id: str,
    directives: list[RememberDirective | RecallDirective],
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
        label = "chain" if item.chain else "key"
        lines.append(f"[RECALL_RESULT {label}={item.key}] {item.payload}")
    block = "\n".join(lines)
    return f"{block}\n\n{_RECALL_FOLLOWUP_HINT}"
