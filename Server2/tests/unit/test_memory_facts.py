from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pytest

from server.memory import facts


class _FakeConn:
    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []
        self.updates: list[tuple[str, Any]] = []

    async def fetchrow(self, query: str, *args: Any) -> dict[str, Any] | None:
        if "SELECT id FROM facts" in query and "active = true" in query:
            user_id, key = args
            for row in self.rows:
                if row["user_id"] == user_id and row["key"] == key and row["active"]:
                    return {"id": row["id"]}
            return None
        if "INSERT INTO facts" in query:
            new_id, user_id, key, value_json, source, confidence = args
            row = {
                "id": new_id,
                "user_id": user_id,
                "key": key,
                "value": value_json,
                "active": True,
                "source": source,
                "confidence": confidence,
                "created_at": datetime.now(timezone.utc),
                "superseded_at": None,
                "superseded_by": None,
            }
            self.rows.append(row)
            return row
        if "active = true" in query and "SELECT * FROM facts" in query:
            user_id, key = args
            for row in self.rows:
                if row["user_id"] == user_id and row["key"] == key and row["active"]:
                    return row
            return None
        return None

    async def fetch(self, query: str, *args: Any) -> list[dict[str, Any]]:
        user_id, key = args
        matched = [r for r in self.rows if r["user_id"] == user_id and r["key"] == key]
        return sorted(matched, key=lambda r: r["created_at"], reverse=True)

    async def execute(self, query: str, *args: Any) -> None:
        if "UPDATE facts" in query:
            new_id, old_id = args
            for row in self.rows:
                if row["id"] == old_id:
                    row["active"] = False
                    row["superseded_by"] = new_id
                    row["superseded_at"] = datetime.now(timezone.utc)


class _FakeAcquire:
    def __init__(self, conn: _FakeConn) -> None:
        self._conn = conn

    async def __aenter__(self) -> _FakeConn:
        return self._conn

    async def __aexit__(self, *args: object) -> None:
        return None


class _FakePool:
    def __init__(self, conn: _FakeConn) -> None:
        self._conn = conn

    def acquire(self) -> _FakeAcquire:
        return _FakeAcquire(self._conn)


class _FakeTransaction:
    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, *args: object) -> None:
        return None


@pytest.fixture(autouse=True)
def _patch_pool_and_embed(monkeypatch: pytest.MonkeyPatch) -> None:
    conn = _FakeConn()

    class ConnWithTx(_FakeConn):
        def transaction(self) -> _FakeTransaction:
            return _FakeTransaction()

    conn = ConnWithTx()
    pool = _FakePool(conn)
    monkeypatch.setattr(facts, "get_pool", lambda: pool)
    monkeypatch.setattr(facts, "embed_text", lambda text: [0.1] * 384)
    monkeypatch.setattr(facts, "upsert_fact_embedding", lambda **_: None)
    async def _noop_dirty(user_id: str) -> None:
        return None

    monkeypatch.setattr(facts, "mark_dirty", _noop_dirty)


@pytest.mark.asyncio
async def test_set_fact_supersedes_active_row() -> None:
    first = await facts.set_fact("u1", "name", "Alex", "user_intent")
    second = await facts.set_fact("u1", "name", "Alexei", "user_intent")

    active = await facts.get_fact("u1", "name")
    assert active is not None
    assert active.id == second.id
    assert active.value == "Alexei"

    chain = await facts.get_chain("u1", "name")
    assert len(chain) == 2
    assert chain[0].active is True
    assert chain[1].id == first.id
    assert chain[1].active is False
