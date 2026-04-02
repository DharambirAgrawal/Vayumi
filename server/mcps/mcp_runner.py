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
#       {"name": "web_search", "description": "...", "when_to_use": "..."},
#       {"name": "set_reminder", "description": "...", "when_to_use": "..."}
#     ],
#     "on_demand": [
#       {"name": "gmail", "description": "...", "requires_auth": true}
#     ]
#   }
#
# CLASS: MCPRunner
#
#   __init__(self, registry_path: str = "server/mcps/mcp_registry.json"):
#     - Loads mcp_registry.json
#     - Discovers and registers MCP handler modules from server/mcps/
#     - self._handlers: dict[str, callable] — maps MCP name to execute function
#
#   def get_registry_summary(self, user_enabled_mcps: list[str]) -> list[dict]:
#     Returns combined list of always-on + user's enabled on-demand MCPs.
#     Each entry: {name, description, when_to_use}
#     This is what goes into the LLM context (~50 tokens).
#
#   async def execute(self, mcp_name: str, params: dict, user_id: str) -> dict:
#     Executes an MCP by name.
#     Steps:
#       1. Look up handler from self._handlers
#       2. Call handler(params, user_id) — all MCPs receive user_id for scoping
#       3. Return result dict
#     Error handling:
#       - Unknown MCP → {"success": False, "error": "Unknown tool: <name>"}
#       - Handler error → {"success": False, "error": str(exception)}
#
#   def register_handler(self, mcp_name: str, handler: callable):
#     Registers a new MCP handler. Called at startup for each MCP module.
#
# FLAG INJECTION (from doc Section 9.3):
#   External services can push flags into context mid-conversation.
#   Format: {"type":"flag_inject", "user_id":str, "source":str, "data":{...}}
#   Flags are stored per-session and injected by context_builder.
#   Example: Gmail MCP monitors inbox, pushes "new_email" flag.
#
# IMPORTS NEEDED:
# =============================================================================

import json
from pathlib import Path


class MCPRunner:
    def __init__(self, registry_path: str = "server/mcps/mcp_registry.json"):
        self.registry_path = Path(registry_path)
        self.registry: dict = {}
        self._handlers: dict[str, callable] = {}

    def get_registry_summary(self, user_enabled_mcps: list[str]) -> list[dict]:
        pass

    async def execute(self, mcp_name: str, params: dict, user_id: str) -> dict:
        pass

    def register_handler(self, mcp_name: str, handler):
        pass
