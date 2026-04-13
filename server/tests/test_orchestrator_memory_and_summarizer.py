from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

SERVER_DIR = Path(__file__).resolve().parents[1]
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

from orchestrator.summarizer import _classify, _extract_items
from orchestrator.tools import memory_ops


class _FakeSearchResult:
    def __init__(self):
        self.context = "ctx"
        self.results = [type("R", (), {"memory_id": "m1", "summary": "hello", "type": "fact", "score": 0.9})()]


class _FakeMemory:
    def search(self, **kwargs):
        return _FakeSearchResult()

    def save(self, **kwargs):
        return {"memory_id": "m2", "success": True}

    def update(self, **kwargs):
        return {"success": True}

    def update_by_query(self, **kwargs):
        return {"success": True, "memory_id": "m3"}

    def delete(self, **kwargs):
        return {"success": True, "deleted_from": ["explicit"]}

    def ingest(self, **kwargs):
        return {"success": True, "memory_id": "m4"}

    def delete_links(self, **kwargs):
        return {"success": True, "deleted_count": 1, "memory_ids": ["m5"]}

    def get_user_model(self, **kwargs):
        return type("Model", (), {"speaker_id": "s", "model_dump": lambda self: {"speaker_id": "s"}})()

    def add_turn(self, **kwargs):
        return None

    def flush_session(self, **kwargs):
        return None


def test_summarizer_classify_and_extract_items() -> None:
    assert _classify("I prefer concise responses") == "preference"
    assert _classify("Meeting tomorrow at 4") == "event"
    assert _classify("My manager is Sam") == "relationship"
    assert _classify("Python is great") == "fact"

    items = _extract_items("Finish quarterly report", "Done and uploaded", ["[CALL] web_search({})", "Kept only final points"])
    assert items
    assert all(len(x.split()) >= 3 for x in items)


def test_memory_ops_success_paths(monkeypatch) -> None:
    monkeypatch.setattr(memory_ops, "_get_memory", lambda speaker_id: _FakeMemory())
    monkeypatch.setattr(memory_ops, "_parse_memory_type", lambda value: None)

    search = memory_ops.memory_search("what did I say", speaker_id="s")
    parsed_search = json.loads(search)
    assert parsed_search["context"] == "ctx"
    assert parsed_search["results"][0]["memory_id"] == "m1"

    save = memory_ops.memory_save("remember this", speaker_id="s", memory_type="fact")
    parsed_save = json.loads(save)
    assert parsed_save["success"] is True

    update = memory_ops.memory_update(speaker_id="s", memory_id="m1", new_content="new")
    assert json.loads(update)["success"] is True

    update_q = memory_ops.memory_update(speaker_id="s", query="old", new_content="new")
    assert json.loads(update_q)["success"] is True

    delete = memory_ops.memory_delete(memory_id="m1", speaker_id="s")
    assert json.loads(delete)["success"] is True

    ingest = memory_ops.memory_ingest(source_type="link", content="https://example.com", speaker_id="s")
    assert json.loads(ingest)["success"] is True

    delete_links = memory_ops.memory_delete_links(speaker_id="s", domain="example.com")
    assert json.loads(delete_links)["deleted_count"] == 1

    model = memory_ops.memory_get_user_model(speaker_id="s")
    assert json.loads(model)["speaker_id"] == "s"

    assert json.loads(memory_ops.memory_add_turn(speaker_id="s", text="hello"))["success"] is True
    assert json.loads(memory_ops.memory_flush_session(speaker_id="s"))["success"] is True


def test_memory_ops_error_path(monkeypatch) -> None:
    monkeypatch.setattr(memory_ops, "_get_memory", lambda speaker_id: None)
    monkeypatch.setattr(memory_ops, "_MEMORY_IMPORT_ERROR", "import failed")

    assert memory_ops.memory_search("q").startswith("ERROR: Memory unavailable")
    assert memory_ops.memory_save("x").startswith("ERROR: Memory unavailable")
    assert memory_ops.memory_update(new_content="x").startswith("ERROR: Memory unavailable")
