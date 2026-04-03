import os
from datetime import datetime, timedelta

import jwt

SECRET_KEY = os.getenv("VAYUMI_JWT_SECRET", "change-me-in-production")
ALGORITHM = "HS256"
TOKEN_EXPIRY_HOURS = 24


def create_token(user_id: str) -> str:
    """Create a signed JWT token for the given user.

    The token carries three claims:
      - ``sub``: the user identifier
      - ``iat``: the UTC timestamp of issuance
      - ``exp``: the UTC expiry timestamp (``TOKEN_EXPIRY_HOURS`` from now)

    Parameters
    ----------
    user_id:
        The unique identifier of the authenticated user.

    Returns
    -------
    str
        An encoded JWT string ready to hand to the client.
    """
    now = datetime.utcnow()
    payload = {
        "sub": user_id,
        "iat": now,
        "exp": now + timedelta(hours=TOKEN_EXPIRY_HOURS),
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def validate_token(token: str) -> str | None:
    """Decode and validate a JWT token, returning the user id on success.

    Parameters
    ----------
    token:
        The raw JWT string received from the client (typically via an
        ``Authorization: Bearer <token>`` header or a WebSocket query
        parameter).

    Returns
    -------
    str | None
        The ``sub`` claim (user id) when the token is valid and not
        expired, or ``None`` when validation fails for any reason:

        - The token has expired (``jwt.ExpiredSignatureError``).
        - The token is malformed or the signature doesn't match
          (``jwt.InvalidTokenError``).
        - The ``sub`` claim is missing from the payload.
    """
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None

    user_id: str | None = payload.get("sub")
    if not user_id:
        return None

    return user_id