from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from pathlib import Path

import pytest

SERVER_DIR = Path(__file__).resolve().parents[1]
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

from orchestrator import supervisor
from orchestrator.tools.web_search import web_search


def _flag_enabled(name: str) -> bool:
    return os.getenv(name, "0").strip().lower() in {"1", "true", "yes", "on"}


def _find_litert_model() -> str | None:
    env_path = os.getenv("LITERT_MODEL_PATH", "").strip()
    if env_path and Path(env_path).exists():
        return env_path

    roots = [Path.cwd() / "vayumi" / "models", Path.cwd() / "models"]
    for root in roots:
        if not root.exists():
            continue
        candidates = sorted(root.rglob("*.litertlm"))
        if candidates:
            return str(candidates[0])
    return None


@pytest.mark.asyncio
async def test_real_local_litert_turn_end_to_end():
    if not _flag_enabled("RUN_REAL_RUNTIME_TESTS"):
        pytest.skip("Set RUN_REAL_RUNTIME_TESTS=1 to run real local LiteRT integration test.")

    model_path = _find_litert_model()
    if not model_path:
        pytest.skip("No .litertlm model found for real runtime test.")

    # Keep cache path writable and deterministic for local runs.
    cache_dir = Path.cwd() / ".litert_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("LITERT_CACHE_DIR", str(cache_dir))

    session_id = "real-runtime-pytest-session"
    t0 = time.perf_counter()
    events = []
    try:
        async for event in supervisor.handle_turn(
            transcript="Please respond with exactly: runtime test passed.",
            session_id=session_id,
            context={"speaker_id": "real-test-user", "input_mode": "chat", "vayumi_state": {}},
            model_hint=model_path,
        ):
            events.append(event)
    finally:
        supervisor.main_worker_store.stop(session_id)

    elapsed = time.perf_counter() - t0

    assert not any(e.get("event") == "error" for e in events)
    assert any(e.get("event") == "agent_thinking" for e in events)
    assert any(e.get("event") == "chatbot_response" for e in events)

    response = next(e for e in events if e.get("event") == "chatbot_response")
    assert response.get("text", "").strip()
    # Real local model path should not be near-instant in typical CPU runtime.
    assert elapsed >= 1.0


@pytest.mark.asyncio
async def test_real_web_search_tool_live_network():
    if not _flag_enabled("RUN_REAL_NETWORK_TESTS"):
        pytest.skip("Set RUN_REAL_NETWORK_TESTS=1 to run live network web_search test.")

    result = await asyncio.to_thread(web_search, "latest ai chip news")
    assert not result.startswith("ERROR:"), result

    payload = json.loads(result)
    assert payload.get("query")
    assert "results" in payload
