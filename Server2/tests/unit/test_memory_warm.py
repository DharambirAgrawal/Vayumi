from __future__ import annotations

import pytest

from server.memory import warm


def test_affects_warm_profile_prefixes() -> None:
    assert warm.affects_warm_profile("name") is True
    assert warm.affects_warm_profile("email.work") is True
    assert warm.affects_warm_profile("scratch.note") is False


@pytest.mark.asyncio
async def test_mark_dirty_invalidates_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    deleted: list[str] = []

    class FakeRedis:
        async def delete(self, key: str) -> None:
            deleted.append(key)

        async def get(self, key: str) -> str | None:
            return None

        async def set(self, key: str, value: str, ex: int) -> None:
            return None

    async def fake_fetch(*args: object, **kwargs: object) -> list:
        return [{"key": "name", "value": '"Alex"'}]

    class FakeConn:
        async def fetch(self, *args: object, **kwargs: object) -> list:
            return await fake_fetch()

    class FakeAcquire:
        async def __aenter__(self) -> FakeConn:
            return FakeConn()

        async def __aexit__(self, *args: object) -> None:
            return None

    class FakePool:
        def acquire(self) -> FakeAcquire:
            return FakeAcquire()

    monkeypatch.setattr(warm, "get_redis", lambda: FakeRedis())
    monkeypatch.setattr(warm, "get_pool", lambda: FakePool())

    await warm.mark_dirty("u1")
    profile = await warm.build_warm_profile("u1")

    assert "name: Alex" in profile
    assert deleted == ["warm_cache:u1"]
