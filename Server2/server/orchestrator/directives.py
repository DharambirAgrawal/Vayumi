from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Literal

from server.logger import get_logger
from server.memory import facts

log = get_logger("orchestrator.directives")

DirectiveKind = Literal["remember", "recall", "recall_chain"]

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
DIRECTIVE_BLOCK_RE = re.compile(
    r'\[(?:REMEMBER|RECALL)(?:\s+chain)?\s+[^\]]+\]',
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


def strip_directives(text: str) -> str:
    cleaned = DIRECTIVE_BLOCK_RE.sub("", text)
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
    return "\n".join(lines)
