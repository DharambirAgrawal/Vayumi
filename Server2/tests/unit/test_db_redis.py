from __future__ import annotations

from server.db.redis import _safe_redis_url


def test_safe_redis_url_masks_credentials() -> None:
    safe = _safe_redis_url("redis://default:secret@example.com:6379/0")

    assert safe == "redis://example.com:6379/0"
    assert "secret" not in safe
