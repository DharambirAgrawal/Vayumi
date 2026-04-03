# =============================================================================
# server/mcps/mcp_runner.py — MCP (Tool) Registry & Executor
# =============================================================================
#
# PURPOSE:
#   Manages and executes MCPs (callable tools). MCPs are fast, atomic operations
#   that return a result. Think of them as APIs Vayumi can call.
#   Each user can enable/disable MCPs independently via their profile.
#
# MCP CATEGORIES:
#
#   ALWAYS-ON MCPs (always in context, Vayumi can call any time):
#     - web_search: Search the web for current information
#     - get_datetime: Current date and time
#     - set_reminder: Create a reminder (scoped to user_id)
#     - get_reminders: List today's reminders (scoped to user_id)
#
#   ON-DEMAND MCPs (registered but not in permanent context, per-user enabled):
#     - gmail: Read/send email (loaded when user enables email integration)
#     - google_calendar: Read/create calendar events
#     - smart_home: Control lights, temperature (when connected)
#
# REGISTRY FORMAT (mcp_registry.json):
#   {
#     "always_on": [
#       {"name": "web_search", "description": "...", "when_to_use": "..."}
#     ],
#     "on_demand": [
#       {"name": "gmail", "description": "...", "requires_auth": true}
#     ]
#   }
#
# =============================================================================

import json
import logging
from pathlib import Path
from typing import Callable, Awaitable, Any

logger = logging.getLogger(__name__)


class MCPRunner:
    """
    Registry and execution engine for Model Context Protocol (MCP) tools.
    
    Loads tool definitions from a JSON registry and binds them to executable
    Python async handlers. Ensures user isolation by passing user_id to
    every execution.
    """

    def __init__(self, registry_path: str = "server/mcps/mcp_registry.json"):
        self.registry_path = Path(registry_path)
        self.registry: dict = {"always_on": [], "on_demand": []}
        
        # Maps mcp_name -> async function
        self._handlers: dict[str, Callable[..., Awaitable[dict]]] = {}
        
        self._load_registry()

    def _load_registry(self) -> None:
        """Load the JSON registry containing tool descriptions for the LLM."""
        if self.registry_path.exists():
            try:
                with open(self.registry_path, "r", encoding="utf-8") as f:
                    self.registry = json.load(f)
                logger.info("Loaded MCP registry from %s", self.registry_path)
            except json.JSONDecodeError as e:
                logger.error("Invalid JSON in MCP registry %s: %s", self.registry_path, e)
            except Exception as e:
                logger.exception("Failed to load MCP registry: %s", e)
        else:
            logger.warning(
                "MCP registry not found at %s. Initialized with empty toolset.",
                self.registry_path
            )

    def get_registry_summary(self, user_enabled_mcps: list[str]) -> list[dict]:
        """
        Build the list of available tools to inject into the LLM's system prompt.
        
        Includes all 'always_on' tools plus any 'on_demand' tools that the
        specific user has explicitly enabled in their profile.
        
        Parameters
        ----------
        user_enabled_mcps : list[str]
            List of on-demand MCP names enabled for the current user.
            
        Returns
        -------
        list[dict]
            List of tool definitions formatted for the LLM context.
        """
        summary = []
        
        # 1. Always-On tools (core system functionality)
        for mcp in self.registry.get("always_on", []):
            summary.append({
                "name": mcp.get("name"),
                "description": mcp.get("description"),
                "when_to_use": mcp.get("when_to_use"),
                "parameters": mcp.get("parameters", {})
            })
            
        # 2. User-specific On-Demand tools (integrations)
        for mcp in self.registry.get("on_demand", []):
            if mcp.get("name") in user_enabled_mcps:
                summary.append({
                    "name": mcp.get("name"),
                    "description": mcp.get("description"),
                    "when_to_use": mcp.get("when_to_use"),
                    "parameters": mcp.get("parameters", {})
                })
                
        return summary

    def list_tools(self, user_enabled_mcps: list[str] | None = None) -> list[dict]:
        """Return only MCPs that are actually available to execute."""
        enabled = set(user_enabled_mcps or [])
        tools: list[dict] = []

        for mcp in self.registry.get("always_on", []):
            name = mcp.get("name")
            if name and name in self._handlers:
                tools.append({
                    "name": name,
                    "description": mcp.get("description"),
                    "when_to_use": mcp.get("when_to_use"),
                    "parameters": mcp.get("parameters", {}),
                })

        for mcp in self.registry.get("on_demand", []):
            name = mcp.get("name")
            if name and name in enabled and name in self._handlers:
                tools.append({
                    "name": name,
                    "description": mcp.get("description"),
                    "when_to_use": mcp.get("when_to_use"),
                    "parameters": mcp.get("parameters", {}),
                })

        return tools

    async def execute(
        self,
        mcp_name: str | None = None,
        params: dict | None = None,
        user_id: str | None = None,
        tool_name: str | None = None,
        context: dict | None = None,
        **kwargs: Any,
    ) -> dict:
        """
        Execute a registered MCP handler safely.
        
        Parameters
        ----------
        mcp_name : str
            The name of the tool to run.
        params : dict
            Arguments parsed from the LLM's tool call.
        user_id : str
            The caller's user ID (enforces data isolation).
        **kwargs : Any
            Additional runtime dependencies to pass to the handler 
            (e.g., sqlite_store).
            
        Returns
        -------
        dict
            Always returns a dict containing at least {"success": bool}.
        """
        resolved_name = mcp_name or tool_name
        if resolved_name is None:
            return {"success": False, "error": "Missing tool name"}

        if user_id is None and isinstance(context, dict):
            user_id = context.get("user_id")

        if user_id is None:
            user_id = "unknown"

        params = params or {}

        if resolved_name not in self._handlers:
            logger.warning("User %s attempted to execute unknown MCP: %s", user_id, resolved_name)
            return {"success": False, "error": f"Unknown tool: {resolved_name}"}
            
        handler = self._handlers[resolved_name]
        
        try:
            logger.debug("Executing MCP '%s' for user '%s' with params: %s", resolved_name, user_id, params)
            
            # Execute the async handler. Kwargs allow caller to inject DB 
            # connections or APIs if they weren't bound via functools.partial.
            result = await handler(params=params, user_id=user_id, **kwargs)
            
            # Ensure the handler returned a dict
            if not isinstance(result, dict):
                logger.warning("MCP '%s' returned %s instead of dict", resolved_name, type(result))
                return {"success": True, "data": result}
                
            return result
            
        except Exception as e:
            logger.exception("Error executing MCP '%s' for user '%s'", resolved_name, user_id)
            return {"success": False, "error": str(e)}

    def register_handler(self, mcp_name: str, handler: Callable[..., Awaitable[dict]]) -> None:
        """
        Register a Python async function to handle an MCP call.
        
        Parameters
        ----------
        mcp_name : str
            The name matching the JSON registry.
        handler : Callable
            The async function to execute.
        """
        if not callable(handler):
            raise ValueError(f"Handler for {mcp_name} must be a callable async function.")
            
        self._handlers[mcp_name] = handler
        logger.debug("Registered MCP handler: %s", mcp_name)

    def has_handler(self, mcp_name: str) -> bool:
        return mcp_name in self._handlers