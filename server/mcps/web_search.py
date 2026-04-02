# =============================================================================
# server/mcps/web_search.py — Web Search MCP (Always-On)
# =============================================================================
#
# PURPOSE:
#   Performs web searches to get current information. This is an always-on MCP
#   — always available in context, Vayumi can call it any time it needs
#   up-to-date information.
#
# WHEN USED:
#   - User asks about something time-sensitive (news, prices, weather)
#   - User asks a factual question the LLM might not know
#   - User explicitly says "search for..." or "look up..."
#   - SearchAgent routes a query through this MCP
#
# FUNCTION: execute(params: dict, user_id: str) -> dict
#
#   params:
#     - "query": str — The search query
#     - "num_results": int (optional, default 5) — Number of results
#
#   Returns:
#     Success:
#       {
#         "success": True,
#         "results": [
#           {"title": str, "url": str, "snippet": str},
#           ...
#         ]
#       }
#     Error:
#       { "success": False, "error": str }
#
# IMPLEMENTATION OPTIONS (Phase 1 — pick one):
#   - DuckDuckGo search (via duckduckgo-search library, no API key needed)
#   - SerpAPI (requires API key, more reliable)
#   - Tavily (designed for AI agents, requires API key)
#
# NOTE: user_id is passed but not used for search itself. It's for
# audit logging and rate limiting per user.
#
# IMPORTS NEEDED:
# =============================================================================


async def execute(params: dict, user_id: str) -> dict:
    pass
