# =============================================================================
# server/auth/router.py — Authentication REST Endpoints
# =============================================================================

from fastapi import APIRouter, HTTPException, Depends, Request
import re
import sqlite3
import uuid

import bcrypt

from server.auth.jwt_handler import create_token, validate_token
from server.auth.models import UserAccount, UserProfile, RegisterRequest, LoginRequest
from server.memory.sqlite_store import SQLiteStore

auth_router = APIRouter()
users_router = APIRouter()


def _build_user_id(display_name: str, sqlite_store: SQLiteStore) -> str:
    """Generate a collision-safe user_id derived from display name."""
    slug = re.sub(r"[^a-z0-9]+", "_", display_name.lower()).strip("_")
    base = f"user_{slug or 'account'}"

    # Try base id first, then append a short random suffix if needed.
    if sqlite_store.get_user(base) is None:
        return base

    for _ in range(5):
        candidate = f"{base}_{uuid.uuid4().hex[:6]}"
        if sqlite_store.get_user(candidate) is None:
            return candidate

    # Extremely unlikely fallback if all retries collide.
    return f"{base}_{uuid.uuid4().hex}"


# --------------------------------------------------------------------------- #
# Dependency: obtain the SQLiteStore instance from app state
# --------------------------------------------------------------------------- #

def _get_sqlite_store(request: Request) -> SQLiteStore:
    """Retrieve the shared :class:`SQLiteStore` instance that was attached
    to the FastAPI application at startup (``app.state.sqlite_store``)."""
    store: SQLiteStore | None = getattr(request.app.state, "sqlite_store", None)
    if store is None:
        raise HTTPException(
            status_code=500,
            detail="SQLite store not initialised",
        )
    return store


# --------------------------------------------------------------------------- #
# Dependency: extract & validate JWT from the Authorization header
# --------------------------------------------------------------------------- #

def _get_current_user_id(request: Request) -> str:
    """Parse the ``Authorization: Bearer <token>`` header and return the
    authenticated ``user_id``.  Raises 401 on any validation failure."""
    auth_header: str | None = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(
            status_code=401,
            detail="Missing or malformed Authorization header",
        )

    token = auth_header[len("Bearer "):]
    user_id = validate_token(token)
    if user_id is None:
        raise HTTPException(
            status_code=401,
            detail="Invalid or expired token",
        )
    return user_id


# --------------------------------------------------------------------------- #
# POST /api/auth/register  (router mounted at prefix /api/auth in main.py)
# --------------------------------------------------------------------------- #

@auth_router.post("/register")
async def register(
    body: RegisterRequest,
    sqlite_store: SQLiteStore = Depends(_get_sqlite_store),
):
    """Register a new user account.

    Steps
    -----
    1. Check that the email is not already taken.
    2. Hash the plaintext password with bcrypt.
    3. Derive a ``user_id`` from the display name.
    4. Persist the new :class:`UserAccount` via the SQLite store.
    5. Return the ``user_id`` and a confirmation message.
    """

    # 1. Email uniqueness check
    existing = sqlite_store.get_user_by_email(body.email)
    if existing is not None:
        raise HTTPException(
            status_code=400,
            detail="An account with this email already exists",
        )

    # 2. Hash password
    password_hash = bcrypt.hashpw(
        body.password.encode("utf-8"),
        bcrypt.gensalt(),
    ).decode("utf-8")

    # 3. Generate collision-safe user_id
    user_id = _build_user_id(body.display_name, sqlite_store)

    # 4. Build account and persist
    account = UserAccount(
        user_id=user_id,
        display_name=body.display_name,
        email=body.email,
        password_hash=password_hash,
        profile=body.profile or {},
    )
    try:
        sqlite_store.create_user(account)
    except sqlite3.IntegrityError:
        # Handle rare race between id generation and insert.
        raise HTTPException(
            status_code=409,
            detail="Could not allocate a unique user id. Please retry.",
        )

    # 5. Success
    return {"user_id": user_id, "message": "registered"}


# --------------------------------------------------------------------------- #
# POST /api/auth/login
# --------------------------------------------------------------------------- #

@auth_router.post("/login")
async def login(
    body: LoginRequest,
    sqlite_store: SQLiteStore = Depends(_get_sqlite_store),
):
    """Authenticate with email + password and receive a JWT.

    Steps
    -----
    1. Look up the user by email.
    2. Verify the password against the stored bcrypt hash.
    3. Mint a JWT containing the ``user_id``.
    4. Return the token alongside basic identity fields.
    """

    # 1. Fetch user
    user: UserAccount | None = sqlite_store.get_user_by_email(body.email)
    if user is None:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    # 2. Verify password
    password_valid = bcrypt.checkpw(
        body.password.encode("utf-8"),
        user.password_hash.encode("utf-8"),
    )
    if not password_valid:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    # 3. Create JWT
    token = create_token(user.user_id)

    # 4. Respond
    return {
        "token": token,
        "user_id": user.user_id,
        "display_name": user.display_name,
    }


# --------------------------------------------------------------------------- #
# GET /api/users/me  (router mounted at prefix /api/users in main.py)
# --------------------------------------------------------------------------- #

@users_router.get("/me")
async def get_me(
    user_id: str = Depends(_get_current_user_id),
    sqlite_store: SQLiteStore = Depends(_get_sqlite_store),
):
    """Return the authenticated user's profile.

    The response deliberately excludes ``password_hash`` and
    ``voice_embedding`` by converting to :class:`UserProfile`.

    Steps
    -----
    1. Validate the JWT (handled by dependency).
    2. Fetch the full :class:`UserAccount` from the store.
    3. Return the API-safe :class:`UserProfile` projection.
    """

    user: UserAccount | None = sqlite_store.get_user(user_id)
    if user is None:
        raise HTTPException(status_code=401, detail="User not found")

    # Strip sensitive fields via the safe projection
    profile: UserProfile = user.to_profile()
    return profile