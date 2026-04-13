from __future__ import annotations

import sys
from pathlib import Path

import pytest

SERVER_DIR = Path(__file__).resolve().parents[1]
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

from agent.runner import AgentRunner
import agent.runner as runner_module


@pytest.mark.asyncio
async def test_agent_runner_maps_orchestrator_events(monkeypatch):
    async def _fake_handle_turn(transcript, session_id, context, model_hint):
        yield {"event": "agent_thinking"}
        yield {"event": "tool_status", "tool": "web_search", "phase": "start", "display": "Searching"}
        yield {"event": "task_progress", "step": "Looking up docs"}
        yield {"event": "chatbot_response", "text": "final response"}

    monkeypatch.setattr(runner_module, "handle_turn", _fake_handle_turn)

    runner = AgentRunner(model="mock")
    out = []
    async for event in runner.run("hello", "session-1", context={"speaker_id": "spk", "input_mode": "chat"}):
        out.append(event)

    types = [e.event_type for e in out]
    assert "thinking" in types
    assert "tool_call" in types
    assert "response_chunk" in types
    assert types[-1] == "response_end"


@pytest.mark.asyncio
async def test_agent_runner_cancel_calls_interrupt(monkeypatch):
    called = []

    async def _fake_interrupt(session_id: str):
        called.append(session_id)

    monkeypatch.setattr(runner_module, "handle_interrupt", _fake_interrupt)

    runner = AgentRunner(model="mock")
    await runner.cancel("session-z")

    assert called == ["session-z"]
