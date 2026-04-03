# =============================================================================
# server/agents/base_agent.py — Base Agent Interface
# =============================================================================
#
# Every agent in the system (Orchestrator, Memory, Task, Search, Persona)
# inherits from BaseAgent.  This module defines:
#
#   AgentContext  — immutable input envelope passed to every agent
#   AgentResult   — structured output envelope returned by every agent
#   BaseAgent     — abstract base with sync run(), background run, lifecycle
#
# Design principles:
#   1. Consistent contracts — all agents speak the same language
#   2. Data isolation      — user_id travels with every context
#   3. Observability       — timing, agent names, error fields built-in
#   4. Safety              — validation on construction, safe defaults
#   5. Extensibility       — metadata/extra dicts for agent-specific payloads
# =============================================================================

from __future__ import annotations

import logging
import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

class Mode(str, Enum):
    """Operating modes the system can be in.

    Using an enum prevents typos (``"noraml"`` vs ``"normal"``) and gives
    IDE autocompletion.  The ``str`` mixin means the value can be compared
    directly with plain strings: ``mode == "normal"`` still works.
    """
    NORMAL = "normal"
    MEETING = "meeting"
    FOCUS = "focus"

    @classmethod
    def from_str(cls, value: str) -> "Mode":
        """Lenient parser — returns NORMAL for unrecognised values."""
        try:
            return cls(value.lower().strip())
        except ValueError:
            logger.warning("Unknown mode '%s', falling back to NORMAL", value)
            return cls.NORMAL


class Sensitivity(str, Enum):
    """Memory sensitivity levels."""
    PRIVATE = "private"
    SHARED = "shared"
    PUBLIC = "public"


# ---------------------------------------------------------------------------
# AgentContext — input envelope
# ---------------------------------------------------------------------------

@dataclass(frozen=False)
class AgentContext:
    """Data envelope passed to every agent's ``run()`` method.

    This is intentionally **mutable** so that the orchestrator can enrich
    the context as it flows through the pipeline (e.g., attaching persona
    data or retrieved memories).  Individual agents should treat fields
    they don't own as read-only by convention.

    Required Fields
    ---------------
    user_id : str
        Authenticated user ID.  All data access is scoped to this.
    input_text : str
        The user's natural-language message for the current turn.

    Optional / Enriched Fields
    --------------------------
    speaker_id : str
        Diarizer label (``"speaker_0"``, ``"speaker_2"``, etc.).
        Defaults to ``user_id`` for text-only sessions.
    session_id : str
        Active session identifier.  Auto-generated if not supplied.
    mode : str | Mode
        Current operating mode.
    working_memory : list[dict]
        Recent conversation turns from the session's sliding window.
    injected_flags : list[dict]
        Pending system flags (email arrived, reminder due, etc.).
    skill_registry : dict
        Available skill names → descriptions.
    mcp_registry : dict
        User's enabled MCP tool servers.
    persona : dict | None
        Persona context for the current speaker (set by PersonaAgent).
    retrieved_memories : list[dict]
        Memories retrieved for this turn (set by MemoryAgent).
    metadata : dict
        Catch-all for agent-specific extra data.
    """

    # --- required ---
    user_id: str
    input_text: str

    # --- identity & session ---
    speaker_id: str = ""
    session_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    mode: str = Mode.NORMAL.value

    # --- conversation state ---
    working_memory: list[dict[str, Any]] = field(default_factory=list)
    injected_flags: list[dict[str, Any]] = field(default_factory=list)

    # --- registries ---
    skill_registry: dict[str, Any] = field(default_factory=dict)
    mcp_registry: dict[str, Any] = field(default_factory=dict)

    # --- enriched by pipeline stages ---
    persona: dict[str, Any] | None = None
    retrieved_memories: list[dict[str, Any]] = field(default_factory=list)

    # --- extensibility ---
    metadata: dict[str, Any] = field(default_factory=dict)

    # --- internal bookkeeping ---
    _created_at: float = field(default_factory=time.time, repr=False)

    def __post_init__(self) -> None:
        # Normalise mode to string value
        if isinstance(self.mode, Mode):
            self.mode = self.mode.value

        # Default speaker_id to user_id when not provided by diarizer
        if not self.speaker_id:
            self.speaker_id = self.user_id

        # Validation
        if not self.user_id:
            raise ValueError("AgentContext requires a non-empty user_id")
        if self.input_text is None:
            self.input_text = ""

    @property
    def mode_enum(self) -> Mode:
        """Return the mode as a typed ``Mode`` enum."""
        return Mode.from_str(self.mode)

    @property
    def age_seconds(self) -> float:
        """Seconds since this context was created — useful for timeout checks."""
        return time.time() - self._created_at

    @property
    def has_flags(self) -> bool:
        return bool(self.injected_flags)

    def clone(self, **overrides: Any) -> "AgentContext":
        """Create a shallow copy with optional field overrides.

        Useful when the orchestrator needs to fan out to multiple agents
        with slightly different contexts (e.g., different input_text for
        a sub-query).
        """
        import dataclasses
        current = dataclasses.asdict(self)
        # Remove private fields that shouldn't be cloned directly
        current.pop("_created_at", None)
        current.update(overrides)
        return AgentContext(**current)


# ---------------------------------------------------------------------------
# AgentResult — output envelope
# ---------------------------------------------------------------------------

@dataclass
class AgentResult:
    """Structured output returned by every agent's ``run()`` method.

    Fields
    ------
    agent_name : str
        Identifier of the agent that produced this result.  Used for
        logging, tracing, and by the orchestrator to merge results.
    success : bool
        Whether the agent considers its execution successful.
    response_text : str | None
        Text response to send to the user.  ``None`` for background-only
        agents or when the agent has nothing to say.
    data : dict
        Arbitrary structured payload (retrieved memories, persona context,
        skill outputs, etc.).  Agents define their own schemas here.
    memories_to_write : list[dict]
        Memory records that should be persisted.  The memory agent picks
        these up asynchronously.
    skills_executed : list[dict]
        Records of skills that ran this turn (name, args, success, latency).
    flags_consumed : list[str]
        IDs of injected flags that this turn acknowledged / resolved.
    follow_up_tasks : list[dict]
        Tasks to enqueue for deferred execution (e.g., a reminder to
        fire in 30 minutes).
    error : str | None
        Human-readable error message if ``success is False``.
    duration_ms : float | None
        Wall-clock time the agent took, in milliseconds.  Set
        automatically by ``BaseAgent._timed_run`` wrapper.
    metadata : dict
        Catch-all for tracing IDs, model names used, token counts, etc.
    """

    agent_name: str = "unknown"
    success: bool = True

    response_text: str | None = None
    data: dict[str, Any] = field(default_factory=dict)

    memories_to_write: list[dict[str, Any]] = field(default_factory=list)
    skills_executed: list[dict[str, Any]] = field(default_factory=list)
    flags_consumed: list[str] = field(default_factory=list)
    follow_up_tasks: list[dict[str, Any]] = field(default_factory=list)

    error: str | None = None
    duration_ms: float | None = None

    metadata: dict[str, Any] = field(default_factory=dict)

    # -- helpers --

    @property
    def has_response(self) -> bool:
        """Does this result carry a user-facing response?"""
        return self.response_text is not None and len(self.response_text.strip()) > 0

    @property
    def has_errors(self) -> bool:
        return not self.success or self.error is not None

    def merge(self, other: "AgentResult") -> "AgentResult":
        """Merge another result into this one (mutates self, returns self).

        Used by the orchestrator to combine outputs from multiple agents.
        The *response_text* is concatenated with a newline separator.
        Lists are extended; dicts are shallow-merged (other wins on conflict).
        """
        if other.response_text:
            if self.response_text:
                self.response_text = f"{self.response_text}\n{other.response_text}"
            else:
                self.response_text = other.response_text

        self.memories_to_write.extend(other.memories_to_write)
        self.skills_executed.extend(other.skills_executed)
        self.flags_consumed.extend(other.flags_consumed)
        self.follow_up_tasks.extend(other.follow_up_tasks)

        # Data dict: shallow merge, other's keys win
        self.data.update(other.data)
        self.metadata.update(other.metadata)

        # Propagate failure
        if not other.success:
            self.success = False
            if other.error:
                existing = self.error or ""
                self.error = f"{existing}; {other.error}".lstrip("; ")

        return self

    @classmethod
    def error_result(cls, agent_name: str, error: str) -> "AgentResult":
        """Factory for a failed result — saves boilerplate in agents."""
        return cls(
            agent_name=agent_name,
            success=False,
            error=error,
        )

    @classmethod
    def empty(cls, agent_name: str = "unknown") -> "AgentResult":
        """Factory for a no-op result (agent had nothing to do)."""
        return cls(agent_name=agent_name, success=True)


# ---------------------------------------------------------------------------
# BaseAgent — abstract base class
# ---------------------------------------------------------------------------

class BaseAgent(ABC):
    """Abstract base for every agent in the system.

    Subclasses **must** implement ``run()``.  They **may** override
    ``run_background()`` for fire-and-forget work, and ``name`` for
    identification.

    The base class provides:
    * ``execute()``         — instrumented wrapper around ``run()``
    * ``execute_background()`` — instrumented wrapper around ``run_background()``
    * ``name``              — agent identifier (class name by default)
    * Logging and timing    — automatic for every invocation
    """

    # ------------------------------------------------------------------ name
    @property
    def name(self) -> str:
        """Human-readable agent name.  Override for a custom label."""
        return self.__class__.__name__

    # --------------------------------------------------------- abstract run
    @abstractmethod
    async def run(self, context: AgentContext) -> AgentResult:
        """Synchronous execution path — the orchestrator awaits this.

        Must be overridden by every concrete agent.  Should return an
        ``AgentResult`` even on failure (use ``AgentResult.error_result``).
        """
        raise NotImplementedError

    # ---------------------------------------------------- background run
    async def run_background(self, context: AgentContext) -> None:
        """Background execution path — fire-and-forget.

        Called *after* the user-facing response has already been sent.
        Default is a no-op.  Override in agents that have post-response
        work (e.g., ``MemoryAgent.process_turn``).
        """
        pass

    # ---------------------------------------------------- instrumented wrappers
    async def execute(self, context: AgentContext) -> AgentResult:
        """Run the agent with timing, logging, and error handling.

        Callers (typically the orchestrator) should prefer ``execute()``
        over calling ``run()`` directly so that instrumentation is
        always applied.
        """
        start = time.monotonic()
        logger.debug("[%s] Starting run for user=%s", self.name, context.user_id)

        try:
            result = await self.run(context)
        except Exception as exc:
            elapsed = (time.monotonic() - start) * 1000
            logger.error(
                "[%s] run() raised after %.1fms: %s",
                self.name,
                elapsed,
                exc,
                exc_info=True,
            )
            result = AgentResult.error_result(
                agent_name=self.name,
                error=f"{type(exc).__name__}: {exc}",
            )
            result.duration_ms = elapsed
            return result

        # Stamp metadata
        elapsed = (time.monotonic() - start) * 1000
        result.duration_ms = elapsed
        if not result.agent_name or result.agent_name == "unknown":
            result.agent_name = self.name

        logger.info(
            "[%s] Completed in %.1fms (success=%s, has_response=%s)",
            self.name,
            elapsed,
            result.success,
            result.has_response,
        )
        return result

    async def execute_background(self, context: AgentContext) -> None:
        """Run background work with error isolation.

        Exceptions are caught and logged — background work must never
        propagate failures to the caller.
        """
        try:
            start = time.monotonic()
            await self.run_background(context)
            elapsed = (time.monotonic() - start) * 1000
            logger.debug(
                "[%s] Background work completed in %.1fms",
                self.name,
                elapsed,
            )
        except Exception as exc:
            logger.error(
                "[%s] Background work failed: %s",
                self.name,
                exc,
                exc_info=True,
            )

    # --------------------------------------------------------- lifecycle hooks
    async def on_startup(self) -> None:
        """Called once when the agent system initialises.

        Override to perform one-time setup (load models, warm caches, etc.).
        """
        pass

    async def on_shutdown(self) -> None:
        """Called once when the agent system is shutting down.

        Override to release resources, flush buffers, etc.
        """
        pass

    # ---------------------------------------------------------- dunder
    def __repr__(self) -> str:
        return f"<{self.name}>"