# =============================================================================
# server/agents/task_agent.py — Task Agent (Multi-Step Execution)
# =============================================================================
#
# PURPOSE:
#   Handles complex, multi-step task execution. Activated when the orchestrator
#   detects a task that requires skill execution, multi-step reasoning, or
#   dependent operations. Uses smarter LLM models (llama-3.3-70b-versatile
#   via Groq, or Gemini for complex reasoning).
#
# WHEN ACTIVATED (from orchestrator intent classification):
#   - Task requires skill execution
#   - Task requires reading skill documentation first
#   - Task has more than 2 dependent steps
#   - Search needed + then reasoning on results
#   - MCP call + interpretation required
#   - Result quality check needed (self-review pass)
#
# MULTI-PASS EXECUTION EXAMPLE (from doc Section 7.2):
#   Turn: "Read the PDF I uploaded and list action items"
#     Pass 1: Orchestrator → intent: complex document task → route to TaskAgent
#     Pass 2: TaskAgent → read skill doc (SKILL.md) → plan steps
#     Pass 3: TaskAgent → execute plan → extract text → summarize
#     Pass 4: Orchestrator → format result → stream to user
#     Background: MemoryAgent logs the result
#
# CLASS: TaskAgent(BaseAgent)
#
#   __init__(self, llm_router, skill_runner, mcp_runner):
#
#   async run(self, context: AgentContext) -> AgentResult:
#     Main execution path. Steps:
#       1. Load relevant skill doc via skill_runner.load_skill_doc(skill_id)
#       2. Plan execution steps via LLM (smart model):
#          - Prompt includes: skill doc + user request + available MCPs
#          - LLM returns structured plan: list of steps
#       3. Execute plan step by step:
#          - For each step: call skill_runner.execute() or mcp_runner.execute()
#          - Collect intermediate results
#          - If a step fails → handle gracefully, report partial result
#       4. Assemble final result from all step outputs
#       5. Return AgentResult with response_text = final result
#
#   async _plan_steps(self, skill_doc: str, user_request: str,
#                     available_mcps: list) -> list[dict]:
#     Uses LLM to generate an execution plan.
#     Each step: {"action": "skill"|"mcp"|"llm", "target": str, "params": dict}
#
#   async _execute_step(self, step: dict, context: AgentContext) -> str:
#     Executes a single step of the plan.
#     Routes to skill_runner, mcp_runner, or LLM based on step["action"].
#
#   async _self_review(self, result: str, original_request: str) -> str:
#     Optional quality check pass. Asks LLM if the result adequately
#     answers the original request. If not, attempts refinement.
#
# DEFERRED TASKS (from doc Section 7.5):
#   When user says "Read this, I'll ask about it later":
#     1. Orchestrator detects: read intent + defer intent
#     2. Instant ack: "Got it, I'll read that and keep it ready."
#     3. TaskAgent runs skill in background → stores result in episodic memory
#        tagged: {user_id, artifact_type: "deferred_read", source_url, summary, created_at}
#     4. Later retrieval: Memory Agent finds it via semantic search + artifact_type filter
#
# IMPORTS NEEDED:
# =============================================================================

from server.agents.base_agent import BaseAgent, AgentContext, AgentResult
from server.llm.router import LLMRouter
from server.skills.skill_runner import SkillRunner
from server.mcps.mcp_runner import MCPRunner


class TaskAgent(BaseAgent):
    def __init__(self, llm_router: LLMRouter, skill_runner: SkillRunner,
                 mcp_runner: MCPRunner):
        self.llm_router = llm_router
        self.skill_runner = skill_runner
        self.mcp_runner = mcp_runner

    async def run(self, context: AgentContext) -> AgentResult:
        pass

    async def _plan_steps(self, skill_doc: str, user_request: str,
                          available_mcps: list) -> list[dict]:
        pass

    async def _execute_step(self, step: dict, context: AgentContext) -> str:
        pass

    async def _self_review(self, result: str, original_request: str) -> str:
        pass
