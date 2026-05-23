from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from typing import Any, Literal

from pydantic import BaseModel, Field

from server.logger import get_logger

log = get_logger("tools.registry")

CapabilityName = Literal["main", "research", "productivity", "comms", "data"]
RiskLevel = Literal["read", "write", "send", "delete", "purchase"]
CostHint = Literal["cheap", "net", "heavy"]

ToolFn = Callable[..., Awaitable["ToolResult"]]


class ToolResult(BaseModel):
    status: Literal[
        "ok",
        "confirmation_required",
        "user_action_required",
        "not_capable",
        "error",
    ]
    summary: str
    data: dict[str, Any] = Field(default_factory=dict)
    confirmation: dict[str, Any] | None = None
    safe_to_show_user: bool = True
    retryable: bool = False


class ToolCard(BaseModel):
    name: str
    capability: CapabilityName
    description: str
    risk: RiskLevel = "read"
    requires_auth: bool = False


class ToolEntry(BaseModel):
    model_config = {"arbitrary_types_allowed": True}

    name: str
    capability: CapabilityName
    description: str
    args_schema: dict[str, Any]
    result_schema: dict[str, Any] | None = None
    fn: ToolFn
    requires_auth: bool = False
    requires_confirmation: bool = False
    risk: RiskLevel = "read"
    cost_hint: CostHint = "cheap"
    timeout_s: int = 30

    def to_card(self) -> ToolCard:
        return ToolCard(
            name=self.name,
            capability=self.capability,
            description=self.description,
            risk=self.risk,
            requires_auth=self.requires_auth,
        )


class ToolCall(BaseModel):
    name: str
    args: dict[str, Any] = Field(default_factory=dict)
    capability: CapabilityName = "main"


class ToolRegistry:
    def __init__(self) -> None:
        self._entries: dict[tuple[str, str], ToolEntry] = {}

    def register(self, entry: ToolEntry) -> None:
        if not entry.name.strip():
            raise ValueError("tool name is required")
        key = (entry.capability, entry.name)
        if key in self._entries:
            raise ValueError(
                f"duplicate tool: capability={entry.capability} name={entry.name}"
            )
        if not entry.args_schema:
            raise ValueError(f"tool {entry.name} requires args_schema")
        self._entries[key] = entry
        log.debug("tools.registered", tool=entry.name, capability=entry.capability)

    def get(self, name: str, capability: str | None = None) -> ToolEntry | None:
        if capability is not None:
            return self._entries.get((capability, name))
        return self._entries.get(("main", name))

    def list_all(self) -> list[ToolEntry]:
        return list(self._entries.values())

    def resolve_for_capability(self, capability: str) -> list[ToolEntry]:
        return [
            entry
            for entry in self._entries.values()
            if entry.capability == capability
        ]

    def search(
        self,
        query: str,
        *,
        capability: str | None = None,
        limit: int = 8,
    ) -> list[ToolCard]:
        needle = query.strip().lower()
        candidates = (
            self.resolve_for_capability(capability)
            if capability
            else self.list_all()
        )
        if not needle:
            return [entry.to_card() for entry in candidates[:limit]]

        scored: list[tuple[int, ToolEntry]] = []
        for entry in candidates:
            hay = f"{entry.name} {entry.description}".lower()
            score = 0
            if needle in entry.name.lower():
                score += 3
            if needle in hay:
                score += 1
            for token in re.split(r"\W+", needle):
                if token and token in hay:
                    score += 1
            if score > 0:
                scored.append((score, entry))
        scored.sort(key=lambda item: (-item[0], item[1].name))
        return [entry.to_card() for _, entry in scored[:limit]]


def validate_tool_args(schema: dict[str, Any], args: dict[str, Any]) -> str | None:
    """Return an error message if args are invalid, else None."""
    required = schema.get("required", [])
    properties = schema.get("properties", {})
    for key in required:
        if key not in args:
            return f"missing required arg: {key}"
    for key, value in args.items():
        if key not in properties:
            continue
        prop = properties[key]
        expected = prop.get("type")
        if expected == "string" and not isinstance(value, str):
            return f"arg {key} must be a string"
        if expected == "integer" and not isinstance(value, int):
            return f"arg {key} must be an integer"
        if expected == "boolean" and not isinstance(value, bool):
            return f"arg {key} must be a boolean"
        if expected == "object" and not isinstance(value, dict):
            return f"arg {key} must be an object"
        if expected == "array" and not isinstance(value, list):
            return f"arg {key} must be an array"
    return None


def render_tool_result_for_prompt(name: str, result: ToolResult) -> str:
    """Compact text block injected into the follow-up Main completion."""
    if result.status == "ok":
        data_preview = result.data
        if "articles" in data_preview and isinstance(data_preview["articles"], list):
            lines = [result.summary]
            for idx, row in enumerate(data_preview["articles"][:5], start=1):
                if not isinstance(row, dict):
                    continue
                title = row.get("title", "")
                url = row.get("url", "")
                status = row.get("status", "")
                text = row.get("text", row.get("snippet", ""))
                if isinstance(text, str) and len(text) > 2000:
                    text = text[:2000] + "…"
                lines.append(f"\n--- Article {idx} ({status}) {title} ---\n{url}\n{text}")
            body = "\n".join(lines)
        elif "text" in data_preview and isinstance(data_preview["text"], str):
            title = data_preview.get("title", "")
            url = data_preview.get("url", "")
            text = data_preview["text"]
            if len(text) > 4000:
                text = text[:4000] + "…"
            body = f"{title}\n{url}\n\n{text}"
        elif "results" in data_preview and isinstance(data_preview["results"], list):
            lines = []
            for idx, row in enumerate(data_preview["results"][:8], start=1):
                if not isinstance(row, dict):
                    continue
                title = row.get("title", "")
                snippet = row.get("snippet", "")
                lines.append(f"{idx}. {title} — {snippet}")
            body = "\n".join(lines) if lines else str(data_preview)
        else:
            body = str(data_preview)
        return f"[TOOL_RESULT tool={name} status=ok] {result.summary}\n{body}"

    return (
        f"[TOOL_RESULT tool={name} status={result.status}] "
        f"{result.summary} data={result.data}"
    )
