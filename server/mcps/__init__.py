"""MCP package bootstrap helpers."""

from __future__ import annotations

import importlib
from typing import Any


def register_builtin_handlers(mcp_runner, sqlite_store=None) -> None:
    """Auto-register built-in MCP handlers from modules in this package."""
    seen: set[str] = set()

    for category in ("always_on", "on_demand"):
        for entry in mcp_runner.registry.get(category, []):
            name = entry.get("name")
            if not name or name in seen:
                continue
            seen.add(name)

            try:
                module = importlib.import_module(f"server.mcps.{name}")
            except ModuleNotFoundError:
                continue

            register_fn = getattr(module, "register_handlers", None)
            if callable(register_fn):
                kwargs: dict[str, Any] = {}
                if sqlite_store is not None:
                    kwargs["sqlite_store"] = sqlite_store
                register_fn(mcp_runner, **kwargs)
                continue

            handlers = getattr(module, "MCP_HANDLERS", None)
            if isinstance(handlers, dict):
                for tool_name, handler in handlers.items():
                    mcp_runner.register_handler(tool_name, handler)
                continue

            execute_fn = getattr(module, "execute", None)
            if callable(execute_fn):
                mcp_runner.register_handler(name, execute_fn)