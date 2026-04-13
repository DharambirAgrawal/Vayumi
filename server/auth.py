"""Authentication and user persistence for Vayumi."""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import time
import uuid
from dataclasses import dataclass
from typing import Optional

import asyncpg
import jwt


@dataclass
class UserRecord:
    id: str
    email: str
    name: Optional[str]


class AuthService:
    def __init__(self, database_url: str, jwt_secret: str, jwt_algorithm: str = "HS256", token_ttl_seconds: int = 7 * 24 * 3600):
        self.database_url = database_url
        self.jwt_secret = jwt_secret
        self.jwt_algorithm = jwt_algorithm
        self.token_ttl_seconds = token_ttl_seconds
        self.pool: Optional[asyncpg.Pool] = None

    async def connect(self) -> None:
        if self.pool is not None:
            return
        self.pool = await asyncpg.create_pool(self.database_url, min_size=1, max_size=5)
        await self._ensure_schema()

    async def close(self) -> None:
        if self.pool is not None:
            await self.pool.close()
            self.pool = None

    async def _ensure_schema(self) -> None:
        assert self.pool is not None
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY,
                    email TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    name TEXT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
                """
            )

    def _hash_password(self, password: str) -> str:
        salt = os.urandom(16)
        digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 200000)
        return f"pbkdf2_sha256$200000${base64.b64encode(salt).decode()}${base64.b64encode(digest).decode()}"

    def _verify_password(self, password: str, stored_hash: str) -> bool:
        try:
            scheme, rounds_str, salt_b64, digest_b64 = stored_hash.split("$", 3)
            if scheme != "pbkdf2_sha256":
                return False
            rounds = int(rounds_str)
            salt = base64.b64decode(salt_b64)
            expected = base64.b64decode(digest_b64)
            actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, rounds)
            return hmac.compare_digest(actual, expected)
        except Exception:
            return False

    async def register(self, email: str, password: str, name: Optional[str]) -> UserRecord:
        if self.pool is None:
            raise RuntimeError("AuthService is not connected")

        normalized_email = email.strip().lower()
        password_hash = self._hash_password(password)

        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO users(id, email, password_hash, name)
                VALUES($1, $2, $3, $4)
                RETURNING id, email, name;
                """,
                str(uuid.uuid4()),
                normalized_email,
                password_hash,
                name,
            )
        return UserRecord(id=row["id"], email=row["email"], name=row["name"])

    async def login(self, email: str, password: str) -> Optional[UserRecord]:
        if self.pool is None:
            raise RuntimeError("AuthService is not connected")

        normalized_email = email.strip().lower()

        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT id, email, name, password_hash
                FROM users
                WHERE email = $1;
                """,
                normalized_email,
            )

        if row is None:
            return None

        if not self._verify_password(password, row["password_hash"]):
            return None

        return UserRecord(id=row["id"], email=row["email"], name=row["name"])

    async def get_user_by_id(self, user_id: str) -> Optional[UserRecord]:
        if self.pool is None:
            raise RuntimeError("AuthService is not connected")

        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT id, email, name
                FROM users
                WHERE id = $1;
                """,
                user_id,
            )

        if row is None:
            return None
        return UserRecord(id=row["id"], email=row["email"], name=row["name"])

    def create_access_token(self, user: UserRecord) -> str:
        now = int(time.time())
        payload = {
            "sub": user.id,
            "email": user.email,
            "iat": now,
            "exp": now + self.token_ttl_seconds,
        }
        return jwt.encode(payload, self.jwt_secret, algorithm=self.jwt_algorithm)

    def decode_access_token(self, token: str) -> dict:
        return jwt.decode(token, self.jwt_secret, algorithms=[self.jwt_algorithm])
