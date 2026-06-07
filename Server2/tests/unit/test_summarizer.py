from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

import pytest

from server.config import reset_settings
from server.engine.pool import (
    ChatCompletionResult,
    CompletionPriority,
    CompletionRequest,
    EnginePool,
)
from server.memory import session as session_mod
from server.memory import summarizer as summ_mod
from server.memory.summarizer import (
    _parse_summarizer_json,
    extract_facts_from_task,
    schedule_session_summarization,
    schedule_task_fact_extraction,
    summarize_session,
)


class _FakeConn:
    def __init__(self) -> None:
        self.turns: list[dict[str, Any]] = []
        self.summary: str | None = None
        self.deleted_ids: list[str] = []

    async def fetch(self, query: str, *args: Any) -> list[dict[str, Any]]:
        if "FROM turns" in query and "ORDER BY created_at ASC" in query:
            session_id = args[0]
            rows = [t for t in self.turns if t["session_id"] == session_id]
            return sorted(rows, key=lambda r: r["created_at"])
        if "SELECT text FROM turns" in query:
            session_id = args[0]
            rows = [t for t in self.turns if t["session_id"] == session_id]
            return sorted(rows, key=lambda r: r["created_at"])
        return []

    async def fetchrow(self, query: str, *args: Any) -> dict[str, Any] | None:
        if "compressed_summary" in query:
            return {"compressed_summary": self.summary}
        return None

    async def execute(self, query: str, *args: Any) -> str:
        if "UPDATE sessions" in query and "compressed_summary" in query:
            self.summary = args[1]
            return "UPDATE 1"
        if "DELETE FROM turns" in query:
            session_id, ids = args
            before = len(self.turns)
            self.turns = [
                t
                for t in self.turns
                if not (t["session_id"] == session_id and str(t["id"]) in ids)
            ]
            deleted = before - len(self.turns)
            self.deleted_ids.extend(ids)
            return f"DELETE {deleted}"
        return "OK"


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


class _RecordingClient:
    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)
        self.calls: list[tuple[CompletionPriority, int | None]] = []

    async def complete_chat(
        self,
        *,
        base_url: str,
        slot_id: int | None,
        request: CompletionRequest,
    ) -> ChatCompletionResult:
        self.calls.append((CompletionPriority.P2_SUMMARIZER, slot_id))
        if not self._responses:
            raise RuntimeError("no more responses")
        return ChatCompletionResult(content=self._responses.pop(0), tool_calls=[])

    def stream_completion(self, **kwargs: object):
        raise NotImplementedError


def _seed_turns(conn: _FakeConn, session_id: str, count: int) -> None:
    now = datetime.now(timezone.utc)
    for idx in range(count):
        conn.turns.append(
            {
                "id": f"00000000-0000-0000-0000-{idx:012d}",
                "session_id": session_id,
                "user_id": "u1",
                "role": "user" if idx % 2 == 0 else "assistant",
                "text": f"Turn {idx} " + ("x" * 200),
                "created_at": now,
            }
        )


@pytest.fixture(autouse=True)
def _low_threshold(monkeypatch: pytest.MonkeyPatch) -> None:
    reset_settings()
    monkeypatch.setenv("SUMMARIZER_TOKEN_THRESHOLD", "100")
    monkeypatch.setenv("SUMMARIZER_RECENT_TURN_KEEP", "2")
    monkeypatch.setenv("SUMMARIZER_MAX_RETRIES", "2")
    reset_settings()


@pytest.fixture
def fake_session_db(monkeypatch: pytest.MonkeyPatch) -> _FakeConn:
    conn = _FakeConn()
    pool = _FakePool(conn)
    monkeypatch.setattr(session_mod, "get_pool", lambda: pool)
    return conn


@pytest.fixture
def fake_facts(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str, object, str]]:
    calls: list[tuple[str, str, object, str]] = []

    async def fake_set_fact(
        user_id: str, key: str, value: object, source: str, **_: object
    ) -> object:
        calls.append((user_id, key, value, source))
        return None

    monkeypatch.setattr(summ_mod.facts, "set_fact", fake_set_fact)
    return calls


def test_parse_summarizer_json_accepts_fenced_block() -> None:
    raw = '```json\n{"summary": "Alex likes ramen.", "facts": []}\n```'
    parsed = _parse_summarizer_json(raw)
    assert parsed is not None
    assert parsed.summary == "Alex likes ramen."


def test_parse_summarizer_json_rejects_invalid() -> None:
    assert _parse_summarizer_json("not json at all") is None


@pytest.mark.asyncio
async def test_summarize_session_writes_summary_and_prunes_turns(
    fake_session_db: _FakeConn,
    fake_facts: list,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _seed_turns(fake_session_db, "s1", 5)
    client = _RecordingClient(
        [
            json_dumps(
                {
                    "summary": "User discussed food and friends.",
                    "facts": [
                        {
                            "key": "name",
                            "value": "Alex",
                            "confidence": 0.95,
                        }
                    ],
                }
            )
        ]
    )
    pool = EnginePool(
        base_url="http://127.0.0.1:8081",
        parallel_slots=4,
        completion_client=client,
    )
    pool.start()

    try:
        ok = await summarize_session("s1", "u1", engine_pool=pool)
    finally:
        await pool.close()

    assert ok is True
    assert fake_session_db.summary == "User discussed food and friends."
    assert len(fake_session_db.turns) == 2
    assert fake_facts == [("u1", "name", "Alex", "summarizer")]
    assert client.calls[0][1] == 3


@pytest.mark.asyncio
async def test_summarize_session_retries_on_invalid_json_then_succeeds(
    fake_session_db: _FakeConn,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _seed_turns(fake_session_db, "s1", 4)
    sleeps: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    monkeypatch.setattr(summ_mod.asyncio, "sleep", fake_sleep)

    client = _RecordingClient(
        [
            "sorry, not json",
            json_dumps({"summary": "Compressed.", "facts": []}),
        ]
    )
    pool = EnginePool(
        base_url="http://127.0.0.1:8081",
        parallel_slots=4,
        completion_client=client,
    )
    pool.start()
    try:
        ok = await summarize_session("s1", "u1", engine_pool=pool)
    finally:
        await pool.close()

    assert ok is True
    assert len(client.calls) == 2
    assert sleeps == [1.0]


@pytest.mark.asyncio
async def test_summarize_session_gives_up_without_pruning_on_total_failure(
    fake_session_db: _FakeConn,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _seed_turns(fake_session_db, "s1", 4)
    async def noop_sleep(_: float) -> None:
        return None

    monkeypatch.setattr(summ_mod.asyncio, "sleep", noop_sleep)

    class _FailClient(_RecordingClient):
        async def complete_chat(self, **kwargs: object) -> ChatCompletionResult:
            raise RuntimeError("engine down")

    pool = EnginePool(
        base_url="http://127.0.0.1:8081",
        parallel_slots=4,
        completion_client=_FailClient([]),
    )
    pool.start()
    try:
        ok = await summarize_session("s1", "u1", engine_pool=pool)
    finally:
        await pool.close()

    assert ok is False
    assert len(fake_session_db.turns) == 4
    assert fake_session_db.summary is None


@pytest.mark.asyncio
async def test_extract_facts_from_task_validates_and_writes(
    fake_facts: list,
) -> None:
    payload = {
        "facts_to_persist": [
            {"key": "relationships.friend_sam", "value": "college roommate", "confidence": 0.9},
            {"key": "", "value": "bad", "confidence": 0.9},
            {"key": "preferences.voice", "value": "warm", "confidence": 0.5},
        ]
    }
    count = await extract_facts_from_task("task-1", "u1", payload)
    assert count == 1
    assert fake_facts[0] == (
        "u1",
        "relationships.friend_sam",
        "college roommate",
        "task:task-1",
    )


@pytest.mark.asyncio
async def test_extract_facts_from_task_empty_payload_is_noop() -> None:
    assert await extract_facts_from_task("t1", "u1", None) == 0


@pytest.mark.asyncio
async def test_schedule_session_summarization_is_non_blocking(
    fake_session_db: _FakeConn,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _seed_turns(fake_session_db, "s1", 5)
    ran = asyncio.Event()

    async def fake_maybe(session_id: str, user_id: str, engine_pool: EnginePool) -> None:
        ran.set()

    monkeypatch.setattr(summ_mod, "_maybe_summarize_session", fake_maybe)
    pool = EnginePool(base_url="http://127.0.0.1:8081", parallel_slots=4)
    pool.start()
    try:
        schedule_session_summarization(
            session_id="s1",
            user_id="u1",
            engine_pool=pool,
        )
        await asyncio.wait_for(ran.wait(), timeout=1.0)
    finally:
        await pool.close()


@pytest.mark.asyncio
async def test_maybe_summarize_skips_when_lock_already_held(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lock = asyncio.Lock()
    await lock.acquire()
    summ_mod._session_locks["s1"] = lock

    calls: list[str] = []

    async def fake_summarize(
        session_id: str, user_id: str, *, engine_pool: EnginePool
    ) -> bool:
        calls.append(session_id)
        return True

    monkeypatch.setattr(summ_mod, "summarize_session", fake_summarize)

    async def fake_estimate(_: str) -> int:
        return 99999

    monkeypatch.setattr(summ_mod, "estimate_history_tokens", fake_estimate)

    pool = EnginePool(base_url="http://127.0.0.1:8081", parallel_slots=4)
    await summ_mod._maybe_summarize_session("s1", "u1", pool)
    lock.release()
    assert calls == []


@pytest.mark.asyncio
async def test_schedule_task_fact_extraction_runs_in_background(
    fake_facts: list,
) -> None:
    schedule_task_fact_extraction(
        task_id="task-99",
        user_id="u1",
        facts_payload=[
            {"key": "name", "value": "Alex", "confidence": 0.95},
        ],
    )
    await asyncio.sleep(0.05)
    assert ("u1", "name", "Alex", "task:task-99") in fake_facts


def json_dumps(payload: dict[str, object]) -> str:
    import json

    return json.dumps(payload)
