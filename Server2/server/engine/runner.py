from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import httpx

from server.logger import get_logger

if TYPE_CHECKING:
    from server.config import Settings

log = get_logger("engine.runner")


@dataclass(frozen=True)
class LlamaServerConfig:
    server_bin: Path
    model_path: Path
    port: int
    parallel_slots: int
    ctx_per_slot: int
    host: str = "127.0.0.1"

    @property
    def ctx_size(self) -> int:
        return self.parallel_slots * self.ctx_per_slot

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"


@dataclass(frozen=True)
class LlamaHealth:
    ok: bool
    status: str


_process: asyncio.subprocess.Process | None = None
_config: LlamaServerConfig | None = None


def config_from_settings(settings: Settings) -> LlamaServerConfig:
    return LlamaServerConfig(
        server_bin=Path(settings.llama_server_bin),
        model_path=Path(settings.llama_model_path),
        port=settings.llama_port,
        parallel_slots=settings.llama_parallel_slots,
        ctx_per_slot=settings.llama_ctx_per_slot,
    )


def build_llama_command(config: LlamaServerConfig) -> list[str]:
    return [
        str(config.server_bin),
        "-m",
        str(config.model_path),
        "--port",
        str(config.port),
        "-np",
        str(config.parallel_slots),
        "--ctx-size",
        str(config.ctx_size),
        "--slot-prompt-similarity",
        "0.0",
        "--jinja",
    ]


async def start_llama_server(config: LlamaServerConfig) -> asyncio.subprocess.Process:
    global _config, _process

    if _process is not None and _process.returncode is None:
        return _process

    _validate_paths(config)
    command = build_llama_command(config)
    log.info(
        "llama.starting",
        bin=str(config.server_bin),
        model=str(config.model_path),
        port=config.port,
        parallel_slots=config.parallel_slots,
        ctx_size=config.ctx_size,
    )

    _process = await asyncio.create_subprocess_exec(
        *command,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    _config = config

    try:
        await _wait_until_healthy(config)
    except Exception:
        await stop_llama_server()
        raise

    log.info("llama.ready", port=config.port)
    return _process


async def stop_llama_server() -> None:
    global _config, _process

    process = _process
    _process = None
    _config = None

    if process is None or process.returncode is not None:
        return

    log.info("llama.stopping", pid=process.pid)
    process.terminate()
    try:
        await asyncio.wait_for(process.wait(), timeout=10)
    except asyncio.TimeoutError:
        log.warning("llama.kill", pid=process.pid)
        process.kill()
        await process.wait()
    log.info("llama.stopped")


async def health_check(config: LlamaServerConfig | None = None) -> LlamaHealth:
    target = config or _config
    if target is None:
        return LlamaHealth(ok=False, status="not_started")

    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            response = await client.get(f"{target.base_url}/health")
    except httpx.HTTPError as exc:
        return LlamaHealth(ok=False, status=str(exc))

    status = _health_status(response)
    return LlamaHealth(ok=response.status_code == 200 and status in {"ok", "ready"}, status=status)


def _validate_paths(config: LlamaServerConfig) -> None:
    if not config.server_bin.is_file():
        raise FileNotFoundError(f"LLAMA_SERVER_BIN does not exist: {config.server_bin}")
    if not config.model_path.is_file():
        raise FileNotFoundError(f"LLAMA_MODEL_PATH does not exist: {config.model_path}")


async def _wait_until_healthy(config: LlamaServerConfig) -> None:
    deadline = asyncio.get_running_loop().time() + 60
    last_status = "not_checked"

    while asyncio.get_running_loop().time() < deadline:
        if _process is not None and _process.returncode is not None:
            raise RuntimeError(f"llama-server exited early with code {_process.returncode}")

        health = await health_check(config)
        last_status = health.status
        if health.ok:
            return
        await asyncio.sleep(0.5)

    raise TimeoutError(f"llama-server did not become healthy: {last_status}")


def _health_status(response: httpx.Response) -> str:
    content_type = response.headers.get("content-type", "")
    if "application/json" in content_type:
        try:
            data = response.json()
        except ValueError:
            return response.text.strip().lower()
        raw = data.get("status", data.get("message", ""))
        return str(raw).strip().lower()
    return response.text.strip().lower()
