from __future__ import annotations

from datetime import datetime, timezone

from jose import JWTError
from jose import jwt as jose_jwt
from pydantic import BaseModel

from server.db.redis import get_server1_redis
from server.logger import get_logger

log = get_logger("auth")

_DEV_USER_ID = "dev_user"
_DEV_SESSION_ID = "dev_session"
_FAR_FUTURE = datetime(2099, 12, 31, tzinfo=timezone.utc)


class TokenPayload(BaseModel):
    user_id: str
    session_id: str
    jti: str
    device_type: str
    scopes: list[str]
    exp: datetime


class AuthError(Exception):
    def __init__(self, message: str, code: int = 4401) -> None:
        self.message = message
        self.code = code
        super().__init__(message)


async def verify_token(
    token: str,
    *,
    app_env: str,
    jwt_public_key: str | None,
) -> TokenPayload:
    if app_env == "dev" and jwt_public_key is None:
        return _dev_verify(token)
    return await _prod_verify(token, jwt_public_key)


def _dev_verify(token: str) -> TokenPayload:
    if token != "dev":
        raise AuthError(f"Invalid dev token (expected 'dev', got '{token[:20]}')")
    log.debug("auth.dev_bypass", user_id=_DEV_USER_ID)
    return TokenPayload(
        user_id=_DEV_USER_ID,
        session_id=_DEV_SESSION_ID,
        jti="dev_jti",
        device_type="web",
        scopes=["*"],
        exp=_FAR_FUTURE,
    )


async def _prod_verify(token: str, jwt_public_key: str | None) -> TokenPayload:
    if not jwt_public_key:
        raise AuthError("JWT_PUBLIC_KEY not configured", code=4500)

    try:
        payload = jose_jwt.decode(
            token,
            jwt_public_key,
            algorithms=["RS256"],
            options={"require_exp": True, "require_iat": True},
        )
    except JWTError as e:
        raise AuthError(f"JWT decode failed: {e}") from e

    for claim in ("sub", "sid", "jti"):
        if claim not in payload:
            raise AuthError(f"Missing required JWT claim: {claim}")

    exp_ts = payload.get("exp", 0)
    exp_dt = datetime.fromtimestamp(exp_ts, tz=timezone.utc)

    token_payload = TokenPayload(
        user_id=payload["sub"],
        session_id=payload["sid"],
        jti=payload["jti"],
        device_type=payload.get("device_type", "unknown"),
        scopes=payload.get("scopes", []),
        exp=exp_dt,
    )

    server1_redis = get_server1_redis()
    if server1_redis is not None:
        blocked = await server1_redis.exists(f"blocklist:{token_payload.jti}")
        if blocked:
            raise AuthError("Token has been revoked")
    else:
        log.warning("auth.blocklist_skipped", reason="SERVER1_REDIS_URL not configured")

    return token_payload
