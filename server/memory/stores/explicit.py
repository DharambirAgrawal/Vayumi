from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from memory.models import MemoryRecord, MemoryType, UserModel

# Allowlists for safe SQL identifier construction
_UPDATABLE_COLUMNS = frozenset({
    "type", "summary", "speaker_id", "created_at", "source_url",
    "blob_path", "chunk_ids", "graph_node_id", "metadata",
})
_SORTABLE_COLUMNS = frozenset({
    "id", "type", "summary", "speaker_id", "created_at",
    "source_url", "blob_path", "graph_node_id",
})
_SORT_DIRECTIONS = frozenset({"ASC", "DESC"})


class ExplicitStore:
    """SQLite-backed canonical index for memory records."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        Path(self.db_path).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS memory_records (
                    id TEXT PRIMARY KEY,
                    type TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    speaker_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    source_url TEXT,
                    blob_path TEXT,
                    chunk_ids TEXT NOT NULL,
                    graph_node_id TEXT,
                    metadata TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS user_models (
                    speaker_id TEXT PRIMARY KEY,
                    model_json TEXT NOT NULL
                )
                """
            )
            conn.commit()

    @staticmethod
    def _to_record(row: sqlite3.Row) -> MemoryRecord:
        return MemoryRecord(
            id=row["id"],
            type=MemoryType(row["type"]),
            summary=row["summary"],
            speaker_id=row["speaker_id"],
            created_at=datetime.fromisoformat(row["created_at"]),
            source_url=row["source_url"],
            blob_path=row["blob_path"],
            chunk_ids=json.loads(row["chunk_ids"] or "[]"),
            graph_node_id=row["graph_node_id"],
            metadata=json.loads(row["metadata"] or "{}"),
        )

    def insert(self, record: MemoryRecord) -> str:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO memory_records
                (id, type, summary, speaker_id, created_at, source_url, blob_path, chunk_ids, graph_node_id, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.id,
                    record.type.value,
                    record.summary,
                    record.speaker_id,
                    record.created_at.isoformat(),
                    record.source_url,
                    record.blob_path,
                    json.dumps(record.chunk_ids),
                    record.graph_node_id,
                    json.dumps(record.metadata),
                ),
            )
            conn.commit()
        return record.id

    def get(self, memory_id: str) -> Optional[MemoryRecord]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM memory_records WHERE id = ?", (memory_id,)).fetchone()
        return self._to_record(row) if row else None

    def update(self, memory_id: str, fields: Dict) -> bool:
        if not fields:
            return True
        unknown = set(fields) - _UPDATABLE_COLUMNS
        if unknown:
            raise ValueError(f"Unknown or non-updatable column(s): {unknown}")
        assignments = []
        values = []
        for key, value in fields.items():
            assignments.append(f"{key} = ?")
            if key in {"chunk_ids", "metadata"}:
                values.append(json.dumps(value))
            elif key == "type" and isinstance(value, MemoryType):
                values.append(value.value)
            else:
                values.append(value)
        values.append(memory_id)
        with self._connect() as conn:
            cur = conn.execute(
                f"UPDATE memory_records SET {', '.join(assignments)} WHERE id = ?",
                tuple(values),
            )
            conn.commit()
            return cur.rowcount > 0

    def delete(self, memory_id: str) -> bool:
        with self._connect() as conn:
            cur = conn.execute("DELETE FROM memory_records WHERE id = ?", (memory_id,))
            conn.commit()
            return cur.rowcount > 0

    @staticmethod
    def _parse_order_by(order_by: str) -> str:
        """Validate and construct a safe ORDER BY clause from an allowlist."""
        parts = order_by.strip().split()
        if len(parts) == 1:
            col, direction = parts[0], "ASC"
        elif len(parts) == 2:
            col, direction = parts[0], parts[1].upper()
        else:
            raise ValueError(f"Invalid order_by expression: {order_by!r}")
        if col not in _SORTABLE_COLUMNS:
            raise ValueError(f"Column {col!r} is not in the sortable columns allowlist")
        if direction not in _SORT_DIRECTIONS:
            raise ValueError(f"Sort direction {direction!r} must be ASC or DESC")
        return f"{col} {direction}"

    def filter(
        self,
        speaker_id: Optional[str] = None,
        type_filter: Optional[MemoryType] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        source_url: Optional[str] = None,
        limit: int = 50,
        order_by: str = "created_at DESC",
    ) -> List[MemoryRecord]:
        clauses = []
        values = []

        if speaker_id:
            clauses.append("speaker_id = ?")
            values.append(speaker_id)
        if type_filter:
            clauses.append("type = ?")
            values.append(type_filter.value if isinstance(type_filter, MemoryType) else str(type_filter))
        if date_from:
            clauses.append("created_at >= ?")
            values.append(date_from)
        if date_to:
            clauses.append("created_at <= ?")
            values.append(date_to)
        if source_url:
            clauses.append("source_url LIKE ?")
            values.append(f"%{source_url}%")

        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        safe_order_by = self._parse_order_by(order_by)
        query = f"SELECT * FROM memory_records {where} ORDER BY {safe_order_by} LIMIT ?"
        values.append(limit)

        with self._connect() as conn:
            rows = conn.execute(query, tuple(values)).fetchall()
        return [self._to_record(r) for r in rows]

    def get_user_model(self, speaker_id: str) -> Dict:
        with self._connect() as conn:
            row = conn.execute("SELECT model_json FROM user_models WHERE speaker_id = ?", (speaker_id,)).fetchone()
        if not row:
            return {}
        return json.loads(row["model_json"])

    def upsert_user_model(self, speaker_id: str, model: UserModel) -> bool:
        payload = {
            "speaker_id": model.speaker_id,
            "communication_style": model.communication_style,
            "preferred_length": model.preferred_length,
            "topics_of_interest": model.topics_of_interest,
            "frequent_people": model.frequent_people,
            "emotional_patterns": model.emotional_patterns,
            "last_updated": model.last_updated.isoformat(),
            "emotional_history": model.emotional_history,
        }
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO user_models (speaker_id, model_json)
                VALUES (?, ?)
                ON CONFLICT(speaker_id) DO UPDATE SET model_json = excluded.model_json
                """,
                (speaker_id, json.dumps(payload)),
            )
            conn.commit()
        return True
