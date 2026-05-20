from __future__ import annotations

from pathlib import Path

import pytest

from server.config import Settings
from server.voice.boot import validate_voice_settings


def test_validate_voice_requires_groq_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    kokoro_dir = tmp_path / "kokoro"
    kokoro_dir.mkdir()
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@localhost/db")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setenv("GROQ_API_KEY", "")
    monkeypatch.setenv("KOKORO_MODEL_DIR", str(kokoro_dir))

    settings = Settings()
    with pytest.raises(ValueError, match="GROQ_API_KEY"):
        validate_voice_settings(settings)


def test_validate_voice_requires_kokoro_dir(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@localhost/db")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    monkeypatch.setenv("KOKORO_MODEL_DIR", "/tmp/does-not-exist-kokoro")

    settings = Settings()
    with pytest.raises(FileNotFoundError, match="KOKORO_MODEL_DIR"):
        validate_voice_settings(settings)
