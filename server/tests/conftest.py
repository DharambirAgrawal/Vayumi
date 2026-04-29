"""Test configuration and fixtures."""
import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from httpx import AsyncClient

import sys
from pathlib import Path

SERVER_ROOT = Path(__file__).resolve().parents[1]
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))

from main import app
from session.manager import SessionManager
from audio.pipeline import AudioPipeline


@pytest.fixture
def client():
    """Test client for sync endpoints."""
    return TestClient(app)


@pytest_asyncio.fixture
async def async_client():
    """Async test client for WebSocket."""
    async with AsyncClient(app=app, base_url="http://test") as client:
        yield client


@pytest_asyncio.fixture
async def session_manager():
    """Create a session manager for testing."""
    manager = SessionManager(session_timeout_seconds=60)
    yield manager


@pytest_asyncio.fixture
async def audio_pipeline():
    """Create an audio pipeline for testing."""
    pipeline = AudioPipeline(sample_rate=16000)
    yield pipeline
