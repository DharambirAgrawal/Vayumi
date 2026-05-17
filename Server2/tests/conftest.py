from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import pytest

os.environ.setdefault("APP_ENV", "dev")
os.environ.setdefault("DATABASE_URL", "postgresql://vayumi:vayumi@localhost:5432/vayumi")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("LANCEDB_DIR", "./data/lancedb_test")


@pytest.fixture
def rsa_keypair() -> tuple[str, str]:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    public_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode()
    return private_pem, public_pem


@pytest.fixture
def fake_token(rsa_keypair: tuple[str, str]) -> tuple[str, str]:
    """Returns (token_string, public_key_pem)."""
    from jose import jwt as jose_jwt

    private_pem, public_pem = rsa_keypair
    now = datetime.now(timezone.utc)
    claims = {
        "sub": "test_user_1",
        "sid": "test_session_1",
        "jti": "test_jti_1",
        "device_type": "web",
        "scopes": ["*"],
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(hours=1)).timestamp()),
    }
    token = jose_jwt.encode(claims, private_pem, algorithm="RS256")
    return token, public_pem
