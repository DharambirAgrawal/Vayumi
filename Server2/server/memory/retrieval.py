from __future__ import annotations

from dataclasses import dataclass

import json

from server.db.lancedb import FACTS_INDEX_TABLE, escape_lancedb_str, get_lancedb
from server.logger import get_logger
from server.memory import facts
from server.memory.embeddings import embed_text_async
from server.memory.meeting_storage import search_meeting_chunks

log = get_logger("memory.retrieval")

_DEFAULT_TOP_K = 5


@dataclass(frozen=True)
class RetrievalFilters:
    user_id: str
    key_prefix: str | None = None
    doc_id: str | None = None


@dataclass(frozen=True)
class Snippet:
    doc_id: str
    key: str
    text: str
    score: float
    citation: str


def _build_where_clause(filters: RetrievalFilters) -> str:
    clauses = [f'user_id = "{escape_lancedb_str(filters.user_id)}"']
    if filters.doc_id:
        clauses.append(f'fact_id = "{escape_lancedb_str(filters.doc_id)}"')
    if filters.key_prefix:
        prefix = escape_lancedb_str(filters.key_prefix)
        clauses.append(f'key LIKE "{prefix}%"')
    return " AND ".join(clauses)


def _distance_to_score(distance: float | None) -> float:
    if distance is None:
        return 1.0
    return max(0.0, 1.0 - float(distance))


def _row_to_snippet(row: dict[str, object], *, score: float) -> Snippet:
    doc_id = str(row["fact_id"])
    key = str(row["key"])
    text = str(row["value_text"])
    citation = f"doc:{doc_id} key={key}"
    return Snippet(
        doc_id=doc_id,
        key=key,
        text=text,
        score=score,
        citation=citation,
    )


def _apply_key_prefix(rows: list[dict[str, object]], prefix: str | None) -> list[dict[str, object]]:
    if not prefix:
        return rows
    return [row for row in rows if str(row.get("key", "")).startswith(prefix)]


async def retrieve(
    query: str,
    filters: RetrievalFilters,
    k: int = _DEFAULT_TOP_K,
) -> list[Snippet]:
    query = query.strip()
    if not query:
        return []
    if k < 1:
        return []

    embedding = await embed_text_async(query)
    table = get_lancedb().open_table(FACTS_INDEX_TABLE)
    where = _build_where_clause(filters)
    limit = k if not filters.key_prefix else max(k * 4, k)
    rows = table.search(embedding).where(where).limit(limit).to_list()
    rows = _apply_key_prefix(rows, filters.key_prefix)[:k]

    snippets = [
        _row_to_snippet(row, score=_distance_to_score(row.get("_distance")))  # type: ignore[arg-type]
        for row in rows
    ]
    log.info(
        "memory.retrieve",
        user_id=filters.user_id,
        query_len=len(query),
        result_count=len(snippets),
        k=k,
    )
    return snippets


async def get_snippet_by_doc_id(user_id: str, doc_id: str) -> Snippet | None:
    doc_id = doc_id.strip()
    if not doc_id:
        return None

    table = get_lancedb().open_table(FACTS_INDEX_TABLE)
    where = _build_where_clause(RetrievalFilters(user_id=user_id, doc_id=doc_id))
    rows = table.search().where(where).limit(1).to_list()
    if not rows:
        log.info("memory.retrieve_doc_miss", user_id=user_id, doc_id=doc_id)
        return None

    snippet = _row_to_snippet(rows[0], score=1.0)
    log.info("memory.retrieve_doc_hit", user_id=user_id, doc_id=doc_id, key=snippet.key)
    return snippet


async def get_meeting_recall(user_id: str, meeting_id: str) -> str:
    """Return meeting summary fact or top chunk snippets for recall."""
    meeting_id = meeting_id.strip()
    if not meeting_id:
        return "(empty meeting id)"

    key = f"meeting:{meeting_id}:summary"
    record = await facts.get_fact(user_id, key)
    if record is not None:
        value = record.value
        if isinstance(value, dict):
            summary = str(value.get("summary", ""))
            items = value.get("action_items") or []
            if items:
                actions = "; ".join(str(i) for i in items)
                return f"{summary} Action items: {actions}"
            return summary
        return json.dumps(value)

    chunks = await search_meeting_chunks(
        meeting_id,
        user_id,
        "meeting summary",
        k=3,
    )
    if not chunks:
        return f"(no meeting data for meeting_id={meeting_id})"

    parts = [chunk.text for chunk in chunks]
    return " | ".join(parts)
