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

    @property
    def is_dev(self) -> bool:
        return self.app_env == "dev"


def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
