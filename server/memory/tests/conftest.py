from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest


SERVER_ROOT = Path(__file__).resolve().parents[2]
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))


@pytest.fixture(autouse=True)
def memory_test_env(monkeypatch):
    monkeypatch.setenv("MEMORY_DISABLE_ENCODER", "1")
    monkeypatch.setenv("MEMORY_DISABLE_WHISPER", "1")
    monkeypatch.setenv("MEMORY_DISABLE_EMBEDDING_TRAINING", "1")
    monkeypatch.setenv("MEMORY_ENABLE_LORA_TRAIN", "0")

    # Disable external HF telemetry/noise during tests.
    monkeypatch.setenv("HF_HUB_DISABLE_TELEMETRY", "1")
    monkeypatch.setenv("TRANSFORMERS_VERBOSITY", "error")

    yield
