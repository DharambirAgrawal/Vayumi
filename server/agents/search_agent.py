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

from __future__ import annotations

import json
import logging
import time
from typing import Any

from server.agents.base_agent import BaseAgent, AgentContext, AgentResult
from server.llm.router import LLMRouter
from server.mcps.mcp_runner import MCPRunner

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

_QUERY_BUILD_SYSTEM_PROMPT = """\
You are a search-query formulator inside an AI assistant.

Given the user's natural-language message (and optionally recent conversation
context), produce the single most effective web-search query string.

Rules:
1. Strip filler words, pleasantries, and conversational fluff.
2. Keep the query concise — ideally 2-8 words.
3. Preserve essential specifics: names, dates, locations, version numbers.
4. If the user asks about something time-sensitive, include a temporal hint
   (e.g. "2025", "today", "latest").
5. If the conversation context clarifies what the user is referring to,
   incorporate that context into the query.
6. Return ONLY the query string — no quotes, no explanation, no markup.\
"""

_QUERY_BUILD_USER_TEMPLATE = """\
=== CONVERSATION CONTEXT (recent turns) ===
{prior_context}

=== USER MESSAGE ===
{user_text}

Produce the search query now.\
"""

_SUMMARIZE_SYSTEM_PROMPT = """\
You are a search-result summariser inside an AI assistant.

Given the user's ORIGINAL QUESTION and a set of WEB SEARCH RESULTS (each with
a title, snippet, and URL), produce a concise, accurate, natural-language
answer.

Rules:
1. Answer the question directly — lead with the most important fact.
2. Synthesise information across multiple results when appropriate.
3. Include source attribution: mention the source name or append
   relevant URLs so the user can verify.
4. If results are contradictory, note the disagreement briefly.
5. If no result adequately answers the question, say so honestly and
   share whatever partial information is available.
6. Keep the answer concise — typically 2-6 sentences unless the topic
   demands more detail.
7. Do NOT fabricate information beyond what the search results provide.\
"""

_SUMMARIZE_USER_TEMPLATE = """\
=== ORIGINAL QUESTION ===
{question}

=== SEARCH RESULTS ===
{formatted_results}

Summarise now.\
"""

# Default MCP tool name for web search.
_WEB_SEARCH_TOOL = "web_search"

# Maximum number of result items to feed into the summarisation prompt
# (guards against token-budget blow-up with very large result sets).
_MAX_RESULTS_FOR_SUMMARY = 10


class SearchAgent(BaseAgent):
    """Handles on-demand web search: query formulation → search → summarisation."""

    def __init__(self, llm_router: LLMRouter, mcp_runner: MCPRunner):
        self.llm_router = llm_router
        self.mcp_runner = mcp_runner

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    async def run(self, context: AgentContext) -> AgentResult:
        """Execute the full search pipeline.

        Steps:
            1. Formulate an optimised search query from the user message.
            2. Execute the search via the ``web_search`` MCP tool.
            3. Summarise results into a natural-language answer with sources.
            4. Return the answer wrapped in an ``AgentResult``.
        """
        start_ts = time.time()
        user_text: str = context.user_message
        metadata: dict[str, Any] = context.metadata or {}

        # ---- 1. Build the search query ---------------------------------
        try:
            query = await self._build_query(user_text, context)
        except Exception as exc:
            logger.error("Query formulation failed: %s", exc, exc_info=True)
            # Fallback: use the raw user text as the query.
            query = self._naive_query_fallback(user_text)
            logger.info("Using naive fallback query: %s", query)

        logger.info("SearchAgent query: %r (from: %.80s…)", query, user_text)

        # ---- 2. Execute the search via MCP -----------------------------
        search_tool = metadata.get("search_tool", _WEB_SEARCH_TOOL)
        raw_results: Any = None
        try:
            raw_results = await self.mcp_runner.execute(
                tool_name=search_tool,
                params={"query": query},
                context={
                    "user_id": getattr(context, "user_id", None),
                    "session_id": getattr(context, "session_id", None),
                },
            )
        except Exception as exc:
            logger.error(
                "Web search MCP call failed: %s", exc, exc_info=True
            )
            return AgentResult(
                response_text=(
                    "I tried to search the web but the search service is "
                    "currently unavailable. Please try again in a moment."
                ),
                metadata={
                    "agent": "search",
                    "query": query,
                    "error": str(exc),
                },
            )

        # ---- 3. Normalise the result set -------------------------------
        results = self._normalise_results(raw_results)

        if not results:
            elapsed = time.time() - start_ts
            return AgentResult(
                response_text=(
                    f'I searched for "{query}" but didn\'t find any relevant '
                    "results. You could try rephrasing your question or "
                    "providing more specific details."
                ),
                metadata={
                    "agent": "search",
                    "query": query,
                    "result_count": 0,
                    "elapsed_seconds": round(elapsed, 3),
                },
            )

        logger.info("Search returned %d result(s)", len(results))

        # ---- 4. Summarise the results ----------------------------------
        try:
            summary = await self._summarize_results(results, user_text)
        except Exception as exc:
            logger.error(
                "Result summarisation failed: %s", exc, exc_info=True
            )
            # Fallback: return raw snippets so the user still gets value.
            summary = self._fallback_format(results, query)

        elapsed = time.time() - start_ts
        logger.info("SearchAgent completed in %.2fs", elapsed)

        return AgentResult(
            response_text=summary,
            metadata={
                "agent": "search",
                "query": query,
                "result_count": len(results),
                "sources": [
                    r.get("url") for r in results if r.get("url")
                ][:_MAX_RESULTS_FOR_SUMMARY],
                "elapsed_seconds": round(elapsed, 3),
            },
        )

    # ------------------------------------------------------------------
    # Query formulation
    # ------------------------------------------------------------------

    async def _build_query(
        self, user_text: str, context: AgentContext | None = None
    ) -> str:
        """Convert a natural-language message into a concise search query.

        Uses the fast/cheap LLM tier for low latency.
        """
        # Build slim prior-context window so the LLM can resolve pronouns
        # and references (e.g. "search for more about *that*").
        prior_context = ""
        if context and hasattr(context, "history") and context.history:
            recent = context.history[-4:]
            lines: list[str] = []
            for msg in recent:
                role = msg.get("role", "user")
                content = msg.get("content", "")
                lines.append(f"{role}: {content[:200]}")
            prior_context = "\n".join(lines)

        user_prompt = _QUERY_BUILD_USER_TEMPLATE.format(
            prior_context=prior_context or "(none)",
            user_text=user_text,
        )

        raw = await self.llm_router.generate(
            messages=[
                {"role": "system", "content": _QUERY_BUILD_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            model_tier="fast",
        )

        query = self._clean_query(raw)

        # Sanity check — if the LLM returned something absurdly long or
        # empty, fall back to the naïve extractor.
        if not query or len(query) > 200:
            query = self._naive_query_fallback(user_text)

        return query

    @staticmethod
    def _clean_query(raw: str) -> str:
        """Strip quotes, whitespace, and stray punctuation from LLM output."""
        text = raw.strip()
        # Remove surrounding quotes the LLM might have added.
        if (text.startswith('"') and text.endswith('"')) or (
            text.startswith("'") and text.endswith("'")
        ):
            text = text[1:-1].strip()
        # Remove markdown artefacts.
        text = text.lstrip("#").strip()
        # Collapse whitespace.
        text = " ".join(text.split())
        return text

    @staticmethod
    def _naive_query_fallback(user_text: str) -> str:
        """Best-effort query extraction without an LLM call.

        Strips common conversational prefixes and truncates.
        """
        text = user_text.strip()
        # Remove common imperative prefixes.
        lower = text.lower()
        for prefix in (
            "search for",
            "look up",
            "google",
            "find me",
            "find out",
            "search",
            "what is",
            "what's",
            "who is",
            "who's",
            "tell me about",
            "can you find",
            "please search",
            "please look up",
        ):
            if lower.startswith(prefix):
                text = text[len(prefix):].strip().lstrip(":")
                break
        # Remove trailing question marks / periods.
        text = text.rstrip("?.!").strip()
        # Truncate to a reasonable length.
        if len(text) > 120:
            text = text[:120]
        return text if text else user_text[:80]

    # ------------------------------------------------------------------
    # Result normalisation
    # ------------------------------------------------------------------

    @staticmethod
    def _normalise_results(raw: Any) -> list[dict[str, str]]:
        """Coerce the MCP search output into a uniform list of dicts.

        Each dict has keys: ``title``, ``snippet``, ``url``.
        Handles several common return shapes from search MCPs:
          - list[dict] with title/snippet/url keys (ideal)
          - list[dict] with name/description/link keys
          - list[str] (bare URLs or snippets)
          - dict with a "results" or "items" key wrapping one of the above
          - raw JSON string wrapping any of the above
        """
        if raw is None:
            return []

        # If the MCP returned a JSON string, parse it first.
        if isinstance(raw, str):
            raw = raw.strip()
            if not raw:
                return []
            try:
                raw = json.loads(raw)
            except json.JSONDecodeError:
                # Treat the whole string as a single snippet.
                return [{"title": "", "snippet": raw[:500], "url": ""}]

        # Unwrap common wrapper keys.
        if isinstance(raw, dict):
            for key in ("results", "items", "data", "organic_results", "web"):
                if key in raw and isinstance(raw[key], list):
                    raw = raw[key]
                    break
            else:
                # Single-result dict — wrap in a list.
                raw = [raw]

        if not isinstance(raw, list):
            return [{"title": "", "snippet": str(raw)[:500], "url": ""}]

        normalised: list[dict[str, str]] = []
        for item in raw[:_MAX_RESULTS_FOR_SUMMARY]:
            if isinstance(item, dict):
                entry: dict[str, str] = {
                    "title": str(
                        item.get("title")
                        or item.get("name")
                        or item.get("heading")
                        or ""
                    ).strip(),
                    "snippet": str(
                        item.get("snippet")
                        or item.get("description")
                        or item.get("body")
                        or item.get("text")
                        or item.get("content")
                        or ""
                    ).strip(),
                    "url": str(
                        item.get("url")
                        or item.get("link")
                        or item.get("href")
                        or ""
                    ).strip(),
                }
                # Skip entries with no meaningful content.
                if entry["title"] or entry["snippet"]:
                    normalised.append(entry)
            elif isinstance(item, str):
                normalised.append(
                    {"title": "", "snippet": item.strip()[:500], "url": ""}
                )

        return normalised

    # ------------------------------------------------------------------
    # Summarisation
    # ------------------------------------------------------------------

    async def _summarize_results(
        self, results: list[dict[str, str]], question: str
    ) -> str:
        """Synthesise search results into a concise, sourced answer.

        Uses the fast LLM tier to keep latency low.
        """
        formatted = self._format_results_for_prompt(results)

        user_prompt = _SUMMARIZE_USER_TEMPLATE.format(
            question=question,
            formatted_results=formatted,
        )

        raw = await self.llm_router.generate(
            messages=[
                {"role": "system", "content": _SUMMARIZE_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            model_tier="fast",
        )

        return raw.strip()

    @staticmethod
    def _format_results_for_prompt(results: list[dict[str, str]]) -> str:
        """Render normalised results into a numbered text block for the LLM."""
        if not results:
            return "(no results)"

        lines: list[str] = []
        for idx, r in enumerate(results[:_MAX_RESULTS_FOR_SUMMARY], start=1):
            parts: list[str] = [f"[{idx}]"]
            if r.get("title"):
                parts.append(f'Title: {r["title"]}')
            if r.get("snippet"):
                parts.append(f'Snippet: {r["snippet"]}')
            if r.get("url"):
                parts.append(f'URL: {r["url"]}')
            lines.append("\n".join(parts))

        return "\n\n".join(lines)

    @staticmethod
    def _fallback_format(
        results: list[dict[str, str]], query: str
    ) -> str:
        """Produce a basic readable output when LLM summarisation fails."""
        header = f'Here\'s what I found for "{query}":\n\n'
        entries: list[str] = []
        for idx, r in enumerate(results[:_MAX_RESULTS_FOR_SUMMARY], start=1):
            parts: list[str] = [f"**{idx}.**"]
            if r.get("title"):
                parts[0] += f' {r["title"]}'
            if r.get("snippet"):
                parts.append(f'  {r["snippet"]}')
            if r.get("url"):
                parts.append(f'  Source: {r["url"]}')
            entries.append("\n".join(parts))
        return header + "\n\n".join(entries)