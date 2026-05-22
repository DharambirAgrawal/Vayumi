from __future__ import annotations

from pydantic import ValidationInfo, field_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}

    # ── App ──────────────────────────────────────────────
    app_env: str = "dev"
    port: int = 8080
    log_level: str = "info"

    # ── Database ─────────────────────────────────────────
    database_url: str
    redis_url: str
    lancedb_dir: str = "./data/lancedb"

    # ── Server 1 handshake (optional in dev) ─────────────
    jwt_public_key: str | None = None
    server1_redis_url: str | None = None

    # ── Engine (code defaults; env only overrides per machine/deploy) ──
    llama_server_bin: str = "./bin/llama-server"
    llama_model_path: str = "./models/gemma-3n-E2B-it-Q4_K_M.gguf"
    llama_port: int = 8081
    llama_parallel_slots: int = 4
    llama_ctx_per_slot: int = 8192

    # ── Voice (code defaults; env only overrides) ─────────
    stt_backend: str = "groq"
    groq_api_key: str | None = None
    kokoro_model_dir: str = "./models/tts"
    kokoro_voice: str = "af_heart"
    self_echo_suppression_delay_ms: int = 1200
    aec_client_suppression_delay_ms: int = 300
    session_singleton_close_code: int = 4001
    session_linger_seconds: int = 60

    # ── Embeddings (optional path for future ONNX export) ──
    bge_model_path: str = "./models/bge-small-en-v1.5.onnx"

    # ── Tools (optional; web_search falls back to DuckDuckGo without key) ──
    tavily_api_key: str | None = None

    @field_validator("app_env")
    @classmethod
    def _validate_app_env(cls, v: str) -> str:
        if v not in ("dev", "prod"):
            raise ValueError("APP_ENV must be 'dev' or 'prod'")
        return v

    @field_validator("jwt_public_key")
    @classmethod
    def _validate_jwt_in_prod(cls, v: str | None, info: ValidationInfo) -> str | None:
        if info.data.get("app_env") == "prod" and not v:
            raise ValueError("JWT_PUBLIC_KEY is required when APP_ENV=prod")
        return v

    @field_validator("server1_redis_url")
    @classmethod
    def _validate_server1_redis_in_prod(cls, v: str | None, info: ValidationInfo) -> str | None:
        if info.data.get("app_env") == "prod" and not v:
            raise ValueError("SERVER1_REDIS_URL is required when APP_ENV=prod")
        return v

    @field_validator("llama_parallel_slots", "llama_ctx_per_slot")
    @classmethod
    def _validate_positive_int(cls, v: int) -> int:
        if v < 1:
            raise ValueError("value must be >= 1")
        return v

    @field_validator("stt_backend")
    @classmethod
    def _validate_stt_backend(cls, v: str) -> str:
        if v not in ("groq", "local"):
            raise ValueError("STT_BACKEND must be 'groq' or 'local'")
        return v

    @property
    def is_dev(self) -> bool:
        return self.app_env == "dev"


def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
