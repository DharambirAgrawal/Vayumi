# =============================================================================
# server/auth/models.py — Auth Data Models
# =============================================================================
#
# PURPOSE:
#   Pydantic models for authentication requests and the UserAccount data class.
#   Used by auth/router.py for request validation and by sqlite_store for
#   representing user data.
#
# MODELS:
#
#   class RegisterRequest(BaseModel):
#     display_name: str          — User's display name (e.g. "Rahul")
#     email: str                 — Email for login (must be unique)
#     password: str              — Plaintext password (will be hashed)
#     profile: dict | None       — Optional JSON profile:
#                                   {occupation, goals, tone_preference, language}
#
#   class LoginRequest(BaseModel):
#     email: str
#     password: str
#
#   class UserAccount:
#     user_id: str               — Unique identifier (e.g. "user_rahul")
#     display_name: str          — "Rahul"
#     email: str                 — Login email
#     password_hash: str         — bcrypt hashed password
#     voice_embedding: bytes | None  — For voice-based identification (enrolled at setup)
#     embedding_model_version: str | None — Track which model generated the voice embedding
#     profile: dict              — JSON: occupation, goals, tone_preference, language
#                                   Stored as TEXT in SQLite, parsed as dict in Python
#     enabled_mcps: list[str]    — JSON array of enabled MCP names
#                                   Default: ["web_search", "set_reminder", "get_reminders", "get_datetime"]
#     created_at: datetime       — Account creation timestamp
#
#   class UserProfile(BaseModel):
#     user_id: str
#     display_name: str
#     email: str
#     profile: dict
#     enabled_mcps: list[str]
#     created_at: datetime
#     (excludes password_hash and voice_embedding for API responses)
# =============================================================================

from datetime import datetime

from pydantic import BaseModel


class RegisterRequest(BaseModel):
    display_name: str
    email: str
    password: str
    profile: dict | None = None


class LoginRequest(BaseModel):
    email: str
    password: str


class UserAccount:
    def __init__(self, user_id: str, display_name: str, email: str,
                 password_hash: str, voice_embedding: bytes | None = None,
                 embedding_model_version: str | None = None,
                 profile: dict | None = None, enabled_mcps: list[str] | None = None,
                 created_at: datetime | None = None):
        self.user_id = user_id
        self.display_name = display_name
        self.email = email
        self.password_hash = password_hash
        self.voice_embedding = voice_embedding
        self.embedding_model_version = embedding_model_version
        self.profile = profile or {}
        self.enabled_mcps = enabled_mcps or ["web_search", "set_reminder", "get_reminders", "get_datetime"]
        self.created_at = created_at or datetime.utcnow()


class UserProfile(BaseModel):
    user_id: str
    display_name: str
    email: str
    profile: dict
    enabled_mcps: list[str]
    created_at: datetime
