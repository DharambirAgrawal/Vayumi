# =============================================================================
# server/auth/jwt_handler.py — JWT Token Creation & Validation
# =============================================================================
#
# PURPOSE:
#   Handles JWT token lifecycle — creation on login and validation on every
#   WebSocket connection and REST API call.
#
# CONFIG:
#   SECRET_KEY: str — loaded from env var VAYUMI_JWT_SECRET (must be set)
#   ALGORITHM: str — "HS256"
#   TOKEN_EXPIRY_HOURS: int — 24 (default, configurable)
#
# FUNCTIONS:
#
#   create_token(user_id: str) -> str:
#     Creates a JWT token containing:
#       - "sub": user_id
#       - "exp": datetime.utcnow() + timedelta(hours=TOKEN_EXPIRY_HOURS)
#       - "iat": datetime.utcnow()
#     Returns encoded JWT string.
#
#   validate_token(token: str) -> str | None:
#     Decodes and validates a JWT token.
#     Returns user_id (from "sub" claim) if valid.
#     Returns None if:
#       - Token is expired (jwt.ExpiredSignatureError)
#       - Token is invalid/malformed (jwt.InvalidTokenError)
#       - "sub" claim is missing
#
# USAGE:
#   - create_token is called by auth/router.py on successful login
#   - validate_token is called by:
#       - ws/handler.py authenticate_connection (WebSocket auth)
#       - auth/router.py get_me endpoint (REST auth)
#
# DEPENDENCIES:
#   - jwt (PyJWT library — import as `import jwt`)
#   - datetime, os
# =============================================================================

import os
from datetime import datetime, timedelta

import jwt

SECRET_KEY = os.getenv("VAYUMI_JWT_SECRET", "change-me-in-production")
ALGORITHM = "HS256"
TOKEN_EXPIRY_HOURS = 24


def create_token(user_id: str) -> str:
    pass


def validate_token(token: str) -> str | None:
    pass
