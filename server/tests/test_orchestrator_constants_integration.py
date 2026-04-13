from __future__ import annotations

import sys
from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parents[1]
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

from orchestrator.constants import OrchestratorEvent, ToolId, WorkerEvent
from orchestrator.main_agent import _run_main_loop
from orchestrator.tools import TOOL_REGISTRY
from orchestrator import ux_emitter


class _QueueCapture:
    def __init__(self):
        self.items: list[dict] = []

    def put(self, item: dict) -> None:
        self.items.append(item)


def test_tool_registry_constant_keys_match_schema_names() -> None:
    # Ensure centralized ToolId constants remain the single source of truth.
    constant_tool_ids = [
        ToolId.WEB_SEARCH,
        ToolId.READ_URL,
        ToolId.URL_SUMMARIZER,
        ToolId.ANALYZE_IMAGE,
        ToolId.TRANSCRIBE_AUDIO,
        ToolId.ANALYZE_VIDEO,
        ToolId.EMAIL_READER,
        ToolId.DOC_GENERATOR,
        ToolId.DATA_ANALYZER,
        ToolId.MEMORY_SEARCH,
        ToolId.MEMORY_SAVE,
        ToolId.MEMORY_UPDATE,
        ToolId.MEMORY_UPDATE_BY_QUERY,
        ToolId.MEMORY_DELETE,
        ToolId.MEMORY_INGEST,
        ToolId.MEMORY_DELETE_LINKS,
        ToolId.MEMORY_GET_USER_MODEL,
        ToolId.MEMORY_ADD_TURN,
        ToolId.MEMORY_FLUSH_SESSION,
    ]

    for tool_id in constant_tool_ids:
        assert tool_id in TOOL_REGISTRY
        schema_name = TOOL_REGISTRY[tool_id]["schema"]["function"]["name"]
        assert schema_name == tool_id


def test_ux_emitter_uses_orchestrator_event_constants() -> None:
    start_payload = ux_emitter.tool_start(ToolId.WEB_SEARCH, {"query": "latest news"})
    done_payload = ux_emitter.tool_done(ToolId.WEB_SEARCH)
    progress_payload = ux_emitter.task_progress("task_1", "desc", "step")

    assert start_payload["event"] == OrchestratorEvent.TOOL_STATUS
    assert done_payload["event"] == OrchestratorEvent.TOOL_STATUS
    assert progress_payload["event"] == OrchestratorEvent.TASK_PROGRESS


def test_main_agent_worker_events_follow_constants() -> None:
    resp_q = _QueueCapture()

    # litert_available=False forces heuristic path and deterministic worker events.
    _run_main_loop(conversation=None, user_message="what time is it", resp_q=resp_q, litert_available=False)

    events = [item.get("event") for item in resp_q.items if isinstance(item, dict)]
    assert WorkerEvent.TOOL_STATUS in events
    assert WorkerEvent.DONE in events
