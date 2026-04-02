# =============================================================================
# server/agents/search_agent.py — Search Agent (On-Demand Web Search)
# =============================================================================
#
# PURPOSE:
#   Decides if a web search is needed, formulates the search query, executes
#   the search via the web_search MCP, and summarizes results for the user.
#   Activated on demand by the orchestrator when it detects the user needs
#   current information the LLM may not have.
#
# WHEN ACTIVATED:
#   - User asks about something time-sensitive (news, prices, current events)
#   - User asks a factual question the LLM is uncertain about
#   - User explicitly says "search for..." or "look up..."
#   - Orchestrator classifies intent as needs_search=True
#
# CLASS: SearchAgent(BaseAgent)
#
#   __init__(self, llm_router, mcp_runner):
#
#   async run(self, context: AgentContext) -> AgentResult:
#     Main execution path. Steps:
#       1. Formulate search query via _build_query(context.input_text)
#          - Uses fast LLM to convert natural language to search query
#          - Example: "What's the weather in Delhi?" → "weather Delhi today"
#       2. Execute search via mcp_runner.execute("web_search", {"query": query})
#       3. Receive search results (list of snippets/URLs)
#       4. Summarize results via _summarize_results(results, original_question)
#          - Uses fast LLM to produce a natural language answer from search results
#       5. Return AgentResult with response_text = summarized answer
#
#   async _build_query(self, user_text: str) -> str:
#     Converts natural language question to an effective search query.
#     Uses llama-3.1-8b-instant (fast, cheap).
#
#   async _summarize_results(self, results: list[dict], question: str) -> str:
#     Summarizes search results into a concise answer.
#     Uses llama-3.1-8b-instant.
#     Includes source attribution where appropriate.
#
# LLM MODEL: llama-3.1-8b-instant (fast, cheap — search is latency-sensitive)
#
# IMPORTS NEEDED:
# =============================================================================

from server.agents.base_agent import BaseAgent, AgentContext, AgentResult
from server.llm.router import LLMRouter
from server.mcps.mcp_runner import MCPRunner


class SearchAgent(BaseAgent):
    def __init__(self, llm_router: LLMRouter, mcp_runner: MCPRunner):
        self.llm_router = llm_router
        self.mcp_runner = mcp_runner

    async def run(self, context: AgentContext) -> AgentResult:
        pass

    async def _build_query(self, user_text: str) -> str:
        pass

    async def _summarize_results(self, results: list[dict], question: str) -> str:
        pass
