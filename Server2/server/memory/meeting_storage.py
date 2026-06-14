from __future__ import annotations

from dataclasses import dataclass

from server.db.lancedb import (
    MEETING_CHUNKS_TABLE,
    escape_lancedb_str,
    get_lancedb,
    upsert_meeting_chunk,
)
from server.logger import get_logger
from server.memory.embeddings import embed_text_async

log = get_logger("memory.meeting_storage")


@dataclass(frozen=True)
class MeetingChunk:
    chunk_id: str
    meeting_id: str
    user_id: str
    speaker: str
    ts_start: float
    ts_end: float
    text: str


def _meeting_where(meeting_id: str, user_id: str) -> str:
    safe_meeting_id = escape_lancedb_str(meeting_id)
    safe_user_id = escape_lancedb_str(user_id)
    return f'meeting_id = "{safe_meeting_id}" AND user_id = "{safe_user_id}"'


async def store_meeting_chunk(
    *,
    chunk_id: str,
    meeting_id: str,
    user_id: str,
    speaker: str,
    ts_start: float,
    ts_end: float,
    text: str,
) -> None:
    text = text.strip()
    if not text:
        return
    embedding = await embed_text_async(text)
    upsert_meeting_chunk(
        chunk_id=chunk_id,
        meeting_id=meeting_id,
        user_id=user_id,
        speaker=speaker,
        ts_start=ts_start,
        ts_end=ts_end,
        text=text,
        embedding=embedding,
    )
    log.info(
        "meeting_storage.stored",
        meeting_id=meeting_id,
        chunk_id=chunk_id,
        chars=len(text),
    )


def list_meeting_chunks(meeting_id: str, user_id: str) -> list[MeetingChunk]:
    table = get_lancedb().open_table(MEETING_CHUNKS_TABLE)
    rows = (
        table.search()
        .where(_meeting_where(meeting_id, user_id))
        .limit(500)
        .to_list()
    )
    chunks = [
        MeetingChunk(
            chunk_id=str(row["chunk_id"]),
            meeting_id=str(row["meeting_id"]),
            user_id=str(row["user_id"]),
            speaker=str(row["speaker"]),
            ts_start=float(row["ts_start"]),
            ts_end=float(row["ts_end"]),
            text=str(row["text"]),
        )
        for row in rows
    ]
    return sorted(chunks, key=lambda c: c.ts_start)


async def search_meeting_chunks(
    meeting_id: str,
    user_id: str,
    query: str,
    *,
    k: int = 5,
) -> list[MeetingChunk]:
    query = query.strip()
    if not query:
        return []
    table = get_lancedb().open_table(MEETING_CHUNKS_TABLE)
    embedding = await embed_text_async(query)
    rows = (
        table.search(embedding)
        .where(_meeting_where(meeting_id, user_id))
        .limit(max(1, k))
        .to_list()
    )
    return [
        MeetingChunk(
            chunk_id=str(row["chunk_id"]),
            meeting_id=str(row["meeting_id"]),
            user_id=str(row["user_id"]),
            speaker=str(row["speaker"]),
            ts_start=float(row["ts_start"]),
            ts_end=float(row["ts_end"]),
            text=str(row["text"]),
        )
        for row in rows
    ]
