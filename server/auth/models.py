# =============================================================================
# server/auth/models.py — Auth Data Models
# =============================================================================

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from pydantic import BaseModel, EmailStr, Field


# ── Request Models ───────────────────────────────────────────────────────────

class RegisterRequest(BaseModel):
    """Incoming payload for ``POST /auth/register``.

    The ``password`` field arrives as plaintext and **must** be hashed
    before storage — never persist this value directly.
    """

    display_name: str = Field(
        ...,
        min_length=1,
        max_length=100,
        examples=["Rahul"],
        description="User's display name",
    )
    email: EmailStr = Field(
        ...,
        examples=["rahul@example.com"],
        description="Email used for login — must be unique across all accounts",
    )
    password: str = Field(
        ...,
        min_length=8,
        max_length=128,
        description="Plaintext password (will be bcrypt-hashed before storage)",
    )
    profile: dict[str, Any] | None = Field(
        default=None,
        description=(
            "Optional JSON profile with keys like occupation, goals, "
            "tone_preference, language"
        ),
        examples=[{
            "occupation": "CS student",
            "goals": ["Build Vayumi", "Learn AI agents"],
            "tone_preference": "casual and direct",
            "language": "en",
        }],
    )


class LoginRequest(BaseModel):
    """Incoming payload for ``POST /auth/login``."""

    email: EmailStr
    password: str


# ── Core User Data Class ────────────────────────────────────────────────────

_DEFAULT_MCPS: list[str] = [
    "web_search",
    "set_reminder",
    "get_reminders",
    "get_datetime",
]


class UserAccount:
    """Internal representation of a persisted user account.

    This is a plain data class (not Pydantic) because it carries sensitive
    fields (``password_hash``, ``voice_embedding``) that should never be
    accidentally serialised into an API response.  Use :class:`UserProfile`
    for safe external representations.

    ``profile`` and ``enabled_mcps`` are stored as JSON TEXT in SQLite;
    the constructor accepts both parsed Python objects **and** raw JSON
    strings for convenience when hydrating rows from the database.
    """

    __slots__ = (
        "user_id",
        "display_name",
        "email",
        "password_hash",
        "voice_embedding",
        "embedding_model_version",
        "profile",
        "enabled_mcps",
        "created_at",
    )

    def __init__(
        self,
        user_id: str,
        display_name: str,
        email: str,
        password_hash: str,
        voice_embedding: bytes | None = None,
        embedding_model_version: str | None = None,
        profile: dict[str, Any] | str | None = None,
        enabled_mcps: list[str] | str | None = None,
        created_at: datetime | str | None = None,
    ):
        self.user_id = user_id
        self.display_name = display_name
        self.email = email
        self.password_hash = password_hash
        self.voice_embedding = voice_embedding
        self.embedding_model_version = embedding_model_version

        # --- profile: accept raw JSON string from SQLite ------------------
        if isinstance(profile, str):
            try:
                profile = json.loads(profile)
            except (json.JSONDecodeError, TypeError):
                profile = {}
        self.profile: dict[str, Any] = profile or {}

        # --- enabled_mcps: accept raw JSON string from SQLite -------------
        if isinstance(enabled_mcps, str):
            try:
                enabled_mcps = json.loads(enabled_mcps)
            except (json.JSONDecodeError, TypeError):
                enabled_mcps = None
        self.enabled_mcps: list[str] = (
            list(enabled_mcps) if enabled_mcps is not None else list(_DEFAULT_MCPS)
        )

        # --- created_at: accept ISO-format string from SQLite -------------
        if isinstance(created_at, str):
            try:
                created_at = datetime.fromisoformat(created_at)
            except (ValueError, TypeError):
                created_at = None
        self.created_at: datetime = created_at or datetime.utcnow()

    # Convenience helpers --------------------------------------------------

    def to_profile(self) -> UserProfile:
        """Return a safe-for-API :class:`UserProfile` representation,
        stripping ``password_hash`` and ``voice_embedding``."""
        return UserProfile(
            user_id=self.user_id,
            display_name=self.display_name,
            email=self.email,
            profile=self.profile,
            enabled_mcps=self.enabled_mcps,
            created_at=self.created_at,
        )

    def __repr__(self) -> str:
        return (
            f"UserAccount(user_id={self.user_id!r}, "
            f"display_name={self.display_name!r}, "
            f"email={self.email!r})"
        )

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, UserAccount):
            return NotImplemented
        return self.user_id == other.user_id

    def __hash__(self) -> int:
        return hash(self.user_id)


# ── Safe API Response Model ─────────────────────────────────────────────────

class UserProfile(BaseModel):
    """Public-safe subset of :class:`UserAccount` suitable for API responses.

    Deliberately excludes ``password_hash``, ``voice_embedding``, and
    ``embedding_model_version``.
    """

    user_id: str
    display_name: str
    email: str
    profile: dict[str, Any] = Field(default_factory=dict)
    enabled_mcps: list[str] = Field(default_factory=lambda: list(_DEFAULT_MCPS))
    created_at: datetime

    model_config = {"from_attributes": True}