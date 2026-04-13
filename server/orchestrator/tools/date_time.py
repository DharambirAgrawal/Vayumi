from __future__ import annotations

from datetime import datetime, timezone


def current_time() -> str:
    """Return current UTC time in HH:MM:SS format for lightweight testing."""
    return datetime.now(timezone.utc).strftime("%H:%M:%S UTC")


def current_date() -> str:
    """Return current UTC date in YYYY-MM-DD format for lightweight testing."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def echo_text(text: str) -> str:
    """Simple placeholder utility to verify tool-calling behavior end-to-end."""
    return f"echo: {text}"
