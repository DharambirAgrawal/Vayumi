# =============================================================================
# server/agents/base_agent.py — Base Agent Interface
# =============================================================================
#
# PURPOSE:
#   Defines the interface that ALL agents must follow. Every agent in the system
#   (Orchestrator, Memory, Task, Search, Persona) inherits from BaseAgent.
#   This ensures consistent interaction contracts across the agent layer.
#
# CLASS: AgentContext
#   Data class passed to every agent's run() method.
#   Fields:
#     user_id: str             — Authenticated user (for data isolation)
#     input_text: str          — The user's message this turn
#     speaker_id: str          — Who is speaking (from diarizer or user_id for text)
#     mode: str                — Current mode ("normal" | "meeting" | "focus")
#     working_memory: list     — Current conversation turns from session
#     injected_flags: list     — Any pending flags (email arrived, reminder due)
#     skill_registry: dict     — Skill registry data (names + descriptions)
#     mcp_registry: dict       — MCP registry data (user's enabled MCPs)
#
# CLASS: AgentResult
#   Data class returned by every agent's run() method.
#   Fields:
#     response_text: str | None    — Text response to send to user (None if background)
#     memories_to_write: list      — Memory records to store (handled by memory agent)
#     skills_executed: list        — Skills that were executed this turn
#     flags_consumed: list         — Flags that were acknowledged/consumed
#     follow_up_tasks: list        — Additional tasks to queue
#
# CLASS: BaseAgent (ABC)
#   Methods:
#     async run(self, context: AgentContext) -> AgentResult:
#       The synchronous execution path. Called when the agent needs to
#       produce a result that the orchestrator waits for.
#       Must be overridden by each agent.
#
#     async run_background(self, context: AgentContext) -> None:
#       The background execution path. Called for fire-and-forget work
#       (e.g., memory writes after response is sent).
#       Default: no-op. Override if the agent has background work.
# =============================================================================

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class AgentContext:
    user_id: str
    input_text: str
    speaker_id: str
    mode: str
    working_memory: list = field(default_factory=list)
    injected_flags: list = field(default_factory=list)
    skill_registry: dict = field(default_factory=dict)
    mcp_registry: dict = field(default_factory=dict)


@dataclass
class AgentResult:
    response_text: str | None = None
    memories_to_write: list = field(default_factory=list)
    skills_executed: list = field(default_factory=list)
    flags_consumed: list = field(default_factory=list)
    follow_up_tasks: list = field(default_factory=list)


class BaseAgent(ABC):
    @abstractmethod
    async def run(self, context: AgentContext) -> AgentResult:
        raise NotImplementedError

    async def run_background(self, context: AgentContext) -> None:
        pass
