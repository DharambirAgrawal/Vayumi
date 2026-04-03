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
# IMPLEMENTATION:
#   Tavily Search API (Optimized for LLM Agents). Requires TAVILY_API_KEY
#   environment variable.
#
# NOTE: user_id is passed but not used for search itself. It's for
# audit logging and rate limiting per user.
#
# =============================================================================

import asyncio
import logging
import os
import aiohttp

logger = logging.getLogger(__name__)

# Tavily API Endpoint
TAVILY_API_URL = "https://api.tavily.com/search"
DEFAULT_TIMEOUT_SECONDS = 15.0


async def execute(params: dict, user_id: str) -> dict:
    """
    Execute a web search using the Tavily API.

    Parameters
    ----------
    params : dict
        Must contain "query". May optionally contain "num_results".
    user_id : str
        The ID of the user requesting the search (used for logging/audit).

    Returns
    -------
    dict
        A dictionary indicating success/failure and containing the results.
    """
    query = params.get("query")
    if not query or not isinstance(query, str):
        logger.warning("Web search failed: Missing or invalid 'query' parameter.")
        return {"success": False, "error": "Missing or invalid 'query' parameter."}

    # Safely parse num_results, defaulting to 5
    try:
        num_results = int(params.get("num_results", 5))
        # Keep bounds reasonable to avoid massive token consumption
        num_results = max(1, min(num_results, 10))
    except (ValueError, TypeError):
        num_results = 5

    api_key = os.getenv("TAVILY_API_KEY")
    if not api_key:
        logger.error("Web search failed: TAVILY_API_KEY is not set in environment.")
        return {"success": False, "error": "Search API key is not configured on the server."}

    logger.info("User %s requested web search for: '%s' (max %d results)", user_id, query, num_results)

    payload = {
        "api_key": api_key,
        "query": query,
        "max_results": num_results,
        "search_depth": "basic",     # "basic" is faster, "advanced" is deeper but slower
        "include_answer": False      # We only need snippets for the LLM to read
    }

    try:
        timeout = aiohttp.ClientTimeout(total=DEFAULT_TIMEOUT_SECONDS)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(TAVILY_API_URL, json=payload) as response:
                
                if response.status != 200:
                    error_text = await response.text()
                    logger.error("Tavily API returned status %d: %s", response.status, error_text)
                    return {
                        "success": False, 
                        "error": f"Search provider returned an error (Status {response.status})."
                    }

                data = await response.json()

        # Map Tavily's response format to our expected standard format
        # Tavily returns items in a "results" list, each with "title", "url", and "content"
        formatted_results = []
        for item in data.get("results", []):
            formatted_results.append({
                "title": item.get("title", "No Title"),
                "url": item.get("url", ""),
                "snippet": item.get("content", "")  # Map 'content' to 'snippet'
            })

        logger.debug("Web search completed successfully with %d results.", len(formatted_results))
        return {
            "success": True,
            "results": formatted_results
        }

    except asyncio.TimeoutError:
        logger.error("Web search timed out after %s seconds.", DEFAULT_TIMEOUT_SECONDS)
        return {"success": False, "error": "Search request timed out. Please try again later."}
    
    except aiohttp.ClientError as e:
        logger.exception("Network error during web search.")
        return {"success": False, "error": f"Network error connecting to search provider: {str(e)}"}
    
    except Exception as e:
        logger.exception("Unexpected error executing web search.")
        return {"success": False, "error": f"An unexpected error occurred: {str(e)}"}


def register_handlers(mcp_runner, **_kwargs) -> None:
    mcp_runner.register_handler("web_search", execute)