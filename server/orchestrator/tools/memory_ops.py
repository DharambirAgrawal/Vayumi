from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, Optional

_MEMORY_INSTANCES: dict[str, Any] = {}
_MEMORY_IMPORT_ERROR: Optional[str] = None


def _ensure_repo_root() -> None:
    repo_root = Path(__file__).resolve().parents[4]
    repo_root_str = str(repo_root)
    if repo_root_str not in sys.path:
        sys.path.append(repo_root_str)


def _get_memory(speaker_id: str):
    global _MEMORY_IMPORT_ERROR

    if speaker_id in _MEMORY_INSTANCES:
        return _MEMORY_INSTANCES[speaker_id]

    try:
        _ensure_repo_root()
        from memory import MemorySystem
        from memory.constants import runtime_memory_settings
    except Exception as exc:  # pragma: no cover - defensive
        _MEMORY_IMPORT_ERROR = str(exc)
        return None

    runtime = runtime_memory_settings()

    instance = MemorySystem(
        speaker_id=speaker_id,
        qdrant_url=runtime["qdrant_url"],
        db_path=runtime["db_path"],
        blob_dir=runtime["blob_dir"],
        collection=runtime["collection"],
        provider_mode=runtime["provider_mode"],
    )
    _MEMORY_INSTANCES[speaker_id] = instance
    return instance


def _parse_memory_type(value: Optional[str]):
    if not value or value == "any":
        return None
    _ensure_repo_root()
    from memory import MemoryType

    try:
        return MemoryType(value)
    except Exception:
        return None


def memory_search(
    query: str,
    speaker_id: str = "default",
    type_filter: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    source_url: Optional[str] = None,
    top_k: int = 5,
) -> str:
    mem = _get_memory(speaker_id)
    if mem is None:
        return f"ERROR: Memory unavailable: {_MEMORY_IMPORT_ERROR or 'unknown import error'}"

    result = mem.search(
        query=query,
        speaker_id=speaker_id,
        type_filter=_parse_memory_type(type_filter),
        date_from=date_from,
        date_to=date_to,
        source_url=source_url,
        top_k=top_k,
    )
    payload: Dict[str, Any] = {
        "context": result.context,
        "results": [
            {
                "memory_id": item.memory_id,
                "summary": item.summary,
                "type": item.type,
                "score": item.score,
            }
            for item in result.results
        ],
    }
    return json.dumps(payload)


def memory_save(
    content: str,
    speaker_id: str = "default",
    memory_type: str = "fact",
    expires_at: Optional[str] = None,
) -> str:
    mem = _get_memory(speaker_id)
    if mem is None:
        return f"ERROR: Memory unavailable: {_MEMORY_IMPORT_ERROR or 'unknown import error'}"

    _ensure_repo_root()
    from memory import MemoryType

    try:
        result = mem.save(
            content=content,
            memory_type=MemoryType(memory_type),
            speaker_id=speaker_id,
            expires_at=expires_at,
        )
        return json.dumps(result)
    except Exception as exc:
        return f"ERROR: {exc}"


def memory_update(
    speaker_id: str = "default",
    memory_id: Optional[str] = None,
    new_content: str = "",
    query: Optional[str] = None,
) -> str:
    mem = _get_memory(speaker_id)
    if mem is None:
        return f"ERROR: Memory unavailable: {_MEMORY_IMPORT_ERROR or 'unknown import error'}"

    try:
        if memory_id:
            result = mem.update(memory_id=memory_id, new_content=new_content, speaker_id=speaker_id)
            return json.dumps(result)
        if query:
            result = mem.update_by_query(query=query, new_content=new_content, speaker_id=speaker_id)
            return json.dumps(result)
        return "ERROR: Provide memory_id or query for memory_update"
    except Exception as exc:
        return f"ERROR: {exc}"


def memory_update_by_query(
    query: str,
    new_content: str,
    speaker_id: str = "default",
) -> str:
    mem = _get_memory(speaker_id)
    if mem is None:
        return f"ERROR: Memory unavailable: {_MEMORY_IMPORT_ERROR or 'unknown import error'}"

    try:
        return json.dumps(mem.update_by_query(query=query, new_content=new_content, speaker_id=speaker_id))
    except Exception as exc:
        return f"ERROR: {exc}"


def memory_delete(
    memory_id: str,
    speaker_id: str = "default",
) -> str:
    mem = _get_memory(speaker_id)
    if mem is None:
        return f"ERROR: Memory unavailable: {_MEMORY_IMPORT_ERROR or 'unknown import error'}"

    try:
        return json.dumps(mem.delete(memory_id=memory_id, speaker_id=speaker_id))
    except Exception as exc:
        return f"ERROR: {exc}"


def memory_ingest(
    source_type: str,
    content: str,
    speaker_id: str = "default",
    date: Optional[str] = None,
    title: Optional[str] = None,
    participants: Optional[list[str]] = None,
) -> str:
    mem = _get_memory(speaker_id)
    if mem is None:
        return f"ERROR: Memory unavailable: {_MEMORY_IMPORT_ERROR or 'unknown import error'}"

    try:
        return json.dumps(
            mem.ingest(
                source_type=source_type,
                content=content,
                speaker_id=speaker_id,
                date=date,
                title=title,
                participants=participants,
            )
        )
    except Exception as exc:
        return f"ERROR: {exc}"


def memory_delete_links(
    speaker_id: str = "default",
    domain: Optional[str] = None,
    delete_all: bool = False,
) -> str:
    mem = _get_memory(speaker_id)
    if mem is None:
        return f"ERROR: Memory unavailable: {_MEMORY_IMPORT_ERROR or 'unknown import error'}"

    try:
        return json.dumps(mem.delete_links(speaker_id=speaker_id, domain=domain, delete_all=delete_all))
    except Exception as exc:
        return f"ERROR: {exc}"


def memory_get_user_model(speaker_id: str = "default") -> str:
    mem = _get_memory(speaker_id)
    if mem is None:
        return f"ERROR: Memory unavailable: {_MEMORY_IMPORT_ERROR or 'unknown import error'}"

    try:
        model = mem.get_user_model(speaker_id=speaker_id)
        return json.dumps(model.model_dump() if hasattr(model, "model_dump") else model.__dict__, default=str)
    except Exception as exc:
        return f"ERROR: {exc}"


def memory_add_turn(speaker_id: str = "default", text: str = "") -> str:
    mem = _get_memory(speaker_id)
    if mem is None:
        return f"ERROR: Memory unavailable: {_MEMORY_IMPORT_ERROR or 'unknown import error'}"

    try:
        mem.add_turn(speaker_id=speaker_id, text=text)
        return json.dumps({"success": True})
    except Exception as exc:
        return f"ERROR: {exc}"


def memory_flush_session(speaker_id: str = "default") -> str:
    mem = _get_memory(speaker_id)
    if mem is None:
        return f"ERROR: Memory unavailable: {_MEMORY_IMPORT_ERROR or 'unknown import error'}"

    try:
        mem.flush_session()
        return json.dumps({"success": True})
    except Exception as exc:
        return f"ERROR: {exc}"
