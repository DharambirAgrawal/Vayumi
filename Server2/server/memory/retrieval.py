from __future__ import annotations

from dataclasses import dataclass

from server.db.lancedb import FACTS_INDEX_TABLE, get_lancedb
from server.logger import get_logger
from server.memory.embeddings import embed_text

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


def _escape_lancedb_str(value: str) -> str:
    return value.replace('"', '\\"').replace("'", "\\'")


def _build_where_clause(filters: RetrievalFilters) -> str:
    clauses = [f'user_id = "{_escape_lancedb_str(filters.user_id)}"']
    if filters.doc_id:
        clauses.append(f'fact_id = "{_escape_lancedb_str(filters.doc_id)}"')
    if filters.key_prefix:
        prefix = _escape_lancedb_str(filters.key_prefix)
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

    embedding = embed_text(query)
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
