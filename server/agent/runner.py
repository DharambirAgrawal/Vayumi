"""AI Agent runner that bridges Vayumi to the orchestrator supervisor."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, AsyncIterator, Dict, Optional

from orchestrator.supervisor import handle_interrupt, handle_turn

logger = logging.getLogger(__name__)


@dataclass
class AgentEvent:
    """Event emitted by the agent during processing."""
    event_type: str  # "thinking", "tool_call", "response_chunk", "response_end", "error"
    content: Optional[str] = None
    tool_name: Optional[str] = None
    tool_args: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


class AgentRunner:
    """Runs orchestrated agent turns for user requests."""

    def __init__(self, model: str = "gpt-3.5-turbo"):
        self.model = model
        self.tools = {}
        logger.info(f"Initialized AgentRunner with model: {model}")

    def register_tool(self, name: str, tool_func, description: str) -> None:
        """Register external tools if needed by custom integrations."""
        self.tools[name] = {
            "func": tool_func,
            "description": description,
        }
        logger.info(f"Registered tool: {name}")

    async def run(
        self,
        transcript: str,
        session_id: str,
        context: Optional[Dict[str, Any] | str] = None,
    ) -> AsyncIterator[AgentEvent]:
        """Run one orchestrated turn and stream normalized AgentEvent entries."""
        logger.info(f"Agent running for session {session_id}: {transcript[:50]}...")

        if isinstance(context, str):
            orchestrator_context: Dict[str, Any] = {"speaker_id": session_id, "input_mode": "chat", "note": context}
        elif isinstance(context, dict):
            orchestrator_context = dict(context)
        else:
            orchestrator_context = {}

        orchestrator_context.setdefault("speaker_id", session_id)
        orchestrator_context.setdefault("input_mode", "chat")
        orchestrator_context.setdefault("vayumi_state", {})

        saw_chunk = False
        async for event in handle_turn(transcript, session_id, orchestrator_context, model_hint=self.model):
            event_type = event.get("event")

            if event_type == "agent_thinking":
                yield AgentEvent(event_type="thinking")
            elif event_type == "tool_status":
                yield AgentEvent(
                    event_type="tool_call",
                    tool_name=event.get("tool"),
                    tool_args={
                        "phase": event.get("phase"),
                        "display": event.get("display"),
                    },
                )
            elif event_type in {"task_progress", "task_complete", "task_waiting", "task_error"}:
                yield AgentEvent(event_type="thinking", content=event.get("step") or event.get("summary") or event.get("question") or event.get("reason"))
            elif event_type == "agent_response_chunk" and event.get("text"):
                saw_chunk = True
                yield AgentEvent(event_type="response_chunk", content=str(event.get("text")))
            elif event_type == "chatbot_response":
                text = str(event.get("text", ""))
                if text and not saw_chunk:
                    for word in text.split():
                        yield AgentEvent(event_type="response_chunk", content=word + " ")
            elif event_type == "error":
                yield AgentEvent(event_type="error", error=event.get("message", "Unknown orchestrator error"))

        yield AgentEvent(event_type="response_end")
        logger.info(f"Agent run complete for session {session_id}")

    async def cancel(self, session_id: str) -> None:
        """Cancel ongoing orchestrator output for a session."""
        logger.info(f"Cancelled agent processing for session {session_id}")
        await handle_interrupt(session_id)

    async def call_tool(self, tool_name: str, args: Dict[str, Any]) -> Any:
        """Call a registered async tool (optional legacy path)."""
        if tool_name not in self.tools:
            logger.error(f"Tool not found: {tool_name}")
            return None

        tool_func = self.tools[tool_name]["func"]
        logger.info(f"Calling tool: {tool_name} with args: {args}")

        try:
            result = await tool_func(**args)
            return result
        except Exception as exc:
            logger.error(f"Error calling tool {tool_name}: {exc}")
            return None
