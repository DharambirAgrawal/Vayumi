# =============================================================================
# server/core/orchestrator.py — Central Consciousness (The Brain)
# =============================================================================
#
# PURPOSE:
#   The orchestrator is the Central Consciousness — it coordinates everything.
#   It is NOT a single LLM call. It receives parsed input, builds context,
#   decides what agents to run, coordinates them, assembles the final response,
#   and streams it back. Think of it as the prefrontal cortex.
#
# PERMANENT SYSTEM PROMPT (~300 tokens, never changes):
#   """
#   You are Vayumi, a superhuman personal AI agent.
#   You are always aware of:
#   - Who you are serving (the authenticated user's profile)
#   - Who is speaking (speaker_id from diarizer)
#   - What mode you are in (normal / meeting / focus)
#   - What context is active (loaded from context engine)
#   - What skills and tools are available (from registry summaries)
#
#   Your job in each turn:
#   1. Understand intent
#   2. Decide: respond directly OR route to skill/tool OR run multi-step
#   3. Never fake capabilities — if you cannot do it, say so honestly
#   4. Respond naturally like a human assistant would
#   5. Be brief unless depth is needed
#   """
#
# CLASS: Orchestrator
#
#   __init__(self, llm_router, context_builder, task_agent, search_agent,
#            memory_agent, skill_runner, mcp_runner):
#     Stores references to all subsystems needed for coordination.
#
#   async run(self, session, context: dict, text: str) -> str | dict:
#     The main orchestration entry point. Called by ws/handler.py process_user_turn.
#     Steps:
#       1. Classify intent via _classify_intent(context, text)
#          Returns IntentResult with fields:
#            - intent_type: "conversation" | "skill" | "mcp" | "complex" | "no_action"
#            - skill_id: str | None (if skill needed)
#            - mcp_name: str | None (if MCP needed)
#            - needs_task_agent: bool
#            - needs_search: bool
#            - response_text: str | None (for direct conversation responses)
#       2. If intent is "conversation" → return response_text directly
#       3. If intent is "no_action" → return None (handler ignores)
#       4. If intent needs task_agent or search → use handle_long_task pattern:
#            a. Generate instant acknowledgment via _generate_instant_ack(intent)
#            b. Run task_agent/skill/search in background
#            c. Return {"ack": ack_text, "result": formatted_result}
#       5. If intent is "mcp" → call mcp_runner.execute(mcp_name, params)
#            Format result naturally → return as string
#       6. If complex → run multi-agent loop:
#            asyncio.gather(task_agent.run(context), memory_agent.process_turn(...))
#            Assemble final result.
#
#   async _classify_intent(self, context: dict, text: str) -> IntentResult:
#     Makes a fast LLM call (llama-3.1-8b-instant via Groq) to classify
#     the user's intent. Uses only the orchestrator system prompt + current
#     context summary + text. Returns IntentResult.
#
#   async _generate_instant_ack(self, intent: IntentResult) -> str:
#     Generates a short acknowledgment like "Sure, let me read that for you."
#     Fast LLM call or template-based (for common intents).
#     Must return within 500ms.
#
#   async format_result(self, session, result: str) -> str:
#     Takes raw result from skill/MCP/agent and formats it naturally
#     for the user. Makes an LLM call to produce natural language.
#
# MULTI-RUN TRIGGERS (from doc Section 7.3):
#   MULTI_RUN_TRIGGERS = [
#     "task requires skill execution",
#     "task requires reading skill documentation first",
#     "task has more than 2 dependent steps",
#     "search needed + then reasoning on results",
#     "MCP call + interpretation required",
#     "result quality check needed (self-review pass)"
#   ]
#
# DATA CLASS: IntentResult
#   intent_type: str
#   skill_id: str | None
#   mcp_name: str | None
#   needs_task_agent: bool
#   needs_search: bool
#   response_text: str | None
#
# IMPORTS NEEDED:
# =============================================================================

import asyncio
from dataclasses import dataclass

from server.llm.router import LLMRouter
from server.core.context_builder import ContextBuilder
from server.agents.task_agent import TaskAgent
from server.agents.search_agent import SearchAgent
from server.agents.memory_agent import MemoryAgent
from server.skills.skill_runner import SkillRunner
from server.mcps.mcp_runner import MCPRunner


SYSTEM_PROMPT = """You are Vayumi, a superhuman personal AI agent.
You are always aware of:
- Who you are serving (the authenticated user's profile)
- Who is speaking (speaker_id from diarizer)
- What mode you are in (normal / meeting / focus)
- What context is active (loaded from context engine)
- What skills and tools are available (from registry summaries)

Your job in each turn:
1. Understand intent
2. Decide: respond directly OR route to skill/tool OR run multi-step
3. Never fake capabilities — if you cannot do it, say so honestly
4. Respond naturally like a human assistant would
5. Be brief unless depth is needed"""


@dataclass
class IntentResult:
    intent_type: str
    skill_id: str | None = None
    mcp_name: str | None = None
    needs_task_agent: bool = False
    needs_search: bool = False
    response_text: str | None = None


class Orchestrator:
    def __init__(self, llm_router: LLMRouter, context_builder: ContextBuilder,
                 task_agent: TaskAgent, search_agent: SearchAgent,
                 memory_agent: MemoryAgent, skill_runner: SkillRunner,
                 mcp_runner: MCPRunner):
        self.llm_router = llm_router
        self.context_builder = context_builder
        self.task_agent = task_agent
        self.search_agent = search_agent
        self.memory_agent = memory_agent
        self.skill_runner = skill_runner
        self.mcp_runner = mcp_runner

    async def run(self, session, context: dict, text: str) -> "str | dict":
        pass

    async def _classify_intent(self, context: dict, text: str) -> IntentResult:
        pass

    async def _generate_instant_ack(self, intent: IntentResult) -> str:
        pass

    async def format_result(self, session, result: str) -> str:
        pass
