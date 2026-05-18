from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx
import pytest

from server.engine.runner import LlamaHealth, LlamaServerConfig, build_llama_command, health_check


def test_build_llama_command_uses_configured_slots_and_context() -> None:
    config = LlamaServerConfig(
        server_bin=Path("/tmp/llama-server"),
        model_path=Path("/tmp/model.gguf"),
        port=8081,
        parallel_slots=4,
        ctx_per_slot=8192,
    )

    command = build_llama_command(config)

    assert command == [
        "/tmp/llama-server",
        "-m",
        "/tmp/model.gguf",
        "--port",
        "8081",
        "-np",
        "4",
        "--ctx-size",
        "32768",
        "--slot-prompt-similarity",
        "0.5",
    ]


@pytest.mark.asyncio
async def test_health_check_accepts_json_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeAsyncClient:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        async def __aenter__(self) -> FakeAsyncClient:
            return self

        async def __aexit__(self, *args: Any) -> None:
            pass

        async def get(self, url: str) -> httpx.Response:
            assert url == "http://127.0.0.1:8081/health"
            return httpx.Response(200, json={"status": "ok"})

    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)
    config = LlamaServerConfig(
        server_bin=Path("/tmp/llama-server"),
        model_path=Path("/tmp/model.gguf"),
        port=8081,
        parallel_slots=4,
        ctx_per_slot=8192,
    )

    health = await health_check(config)

    assert health == LlamaHealth(ok=True, status="ok")


@pytest.mark.asyncio
async def test_health_check_reports_http_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeAsyncClient:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        async def __aenter__(self) -> FakeAsyncClient:
            return self

        async def __aexit__(self, *args: Any) -> None:
            pass

        async def get(self, url: str) -> httpx.Response:
            raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)
    config = LlamaServerConfig(
        server_bin=Path("/tmp/llama-server"),
        model_path=Path("/tmp/model.gguf"),
        port=8081,
        parallel_slots=4,
        ctx_per_slot=8192,
    )

    health = await health_check(config)

    assert health.ok is False
    assert "connection refused" in health.status
