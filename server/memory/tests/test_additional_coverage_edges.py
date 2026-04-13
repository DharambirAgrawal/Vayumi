from __future__ import annotations

import base64

import pytest

from memory import MemorySystem, MemoryType
from memory.errors import MemoryValidationError
from memory.tools import TOOLS


def test_update_by_query_returns_no_match_when_nothing_found(tmp_path):
    mem = MemorySystem(
        speaker_id="zara",
        db_path=str(tmp_path / "no-match.db"),
        blob_dir=str(tmp_path / "blobs"),
        qdrant_url="memory://",
        provider_mode="local",
    )

    out = mem.update_by_query(
        query="nonexistent memory phrase",
        new_content="updated",
        speaker_id="zara",
    )
    assert out["success"] is False
    assert out["reason"] == "no_match"


def test_delete_links_requires_domain_or_delete_all(tmp_path):
    mem = MemorySystem(
        speaker_id="zara",
        db_path=str(tmp_path / "delete-links-guard.db"),
        blob_dir=str(tmp_path / "blobs"),
        qdrant_url="memory://",
        provider_mode="local",
    )

    with pytest.raises(MemoryValidationError):
        mem.delete_links(speaker_id="zara")


def test_link_refresh_updates_summary_and_chunks(tmp_path):
    mem = MemorySystem(
        speaker_id="zara",
        db_path=str(tmp_path / "link-refresh.db"),
        blob_dir=str(tmp_path / "blobs"),
        qdrant_url="memory://",
        provider_mode="local",
    )

    mem.link_ingester.fetch = lambda url: "initial body"  # type: ignore[method-assign]
    ing = mem.ingest("link", "https://example.com/docs", speaker_id="zara")
    first = mem.explicit.get(ing.memory_id)
    assert first is not None
    old_chunks = list(first.chunk_ids)

    mem.link_ingester.fetch = lambda url: "refreshed body with new facts"  # type: ignore[method-assign]
    refreshed = mem.link_ingester.refresh(ing.memory_id)
    assert refreshed.success is True

    second = mem.explicit.get(ing.memory_id)
    assert second is not None
    assert "refreshed body" in second.summary
    assert second.chunk_ids
    assert second.chunk_ids != old_chunks


def test_multimodal_blocks_load_only_available_media(tmp_path):
    mem = MemorySystem(
        speaker_id="zara",
        db_path=str(tmp_path / "multimodal.db"),
        blob_dir=str(tmp_path / "blobs"),
        qdrant_url="memory://",
        provider_mode="local",
    )

    image_payload = base64.b64encode(b"\x89PNG\r\n\x1a\n").decode("ascii")
    audio_payload = base64.b64encode(b"audio-content" * 120).decode("ascii")

    mem.ingest("image", image_payload, speaker_id="zara", title="img")
    mem.ingest("audio", audio_payload, speaker_id="zara", title="aud")
    mem.save("Plain text fact only", MemoryType.FACT)

    results = mem.search("img aud plain", top_k=10).results
    blocks = mem.retrieval.load_multimodal_blocks(results)
    assert blocks
    types = {b["type"] for b in blocks}
    assert "image" in types
    assert "audio" in types


def test_tools_contract_contains_required_operations():
    names = {t["name"] for t in TOOLS}
    required = {
        "memory_search",
        "memory_ingest",
        "memory_save",
        "memory_delete",
        "memory_update",
        "memory_update_by_query",
        "memory_delete_links",
        "memory_get_user_model",
        "memory_add_turn",
        "memory_flush_session",
    }
    assert required.issubset(names)


def test_all_memory_types_share_one_sqlite_db(tmp_path):
    db_path = tmp_path / "memory.db"
    blob_dir = tmp_path / "blobs"

    mem = MemorySystem(
        speaker_id="nora",
        db_path=str(db_path),
        blob_dir=str(blob_dir),
        qdrant_url="memory://",
        provider_mode="local",
    )

    mem.link_ingester.fetch = lambda url: "fetched link content"  # type: ignore[method-assign]

    mem.save("Nora likes concise updates", MemoryType.PREFERENCE)
    mem.save("Nora joined standup at 10", MemoryType.EVENT)
    mem.save("Nora works with Arun", MemoryType.RELATIONSHIP)
    mem.ingest("link", "https://example.com/blog", speaker_id="nora")
    mem.ingest("file", base64.b64encode(b"name,role\nNora,Lead\n").decode("ascii"), speaker_id="nora")
    mem.ingest("image", base64.b64encode(b"\x89PNG\r\n\x1a\n").decode("ascii"), speaker_id="nora")
    mem.ingest("audio", base64.b64encode(b"audio-bytes" * 128).decode("ascii"), speaker_id="nora")
    mem.ingest("meeting", "[nora 0] action: publish notes", speaker_id="nora", participants=["nora"])

    rows = mem.explicit.filter(speaker_id="nora", limit=200)
    row_types = {row.type for row in rows}
    assert {
        MemoryType.PREFERENCE,
        MemoryType.EVENT,
        MemoryType.RELATIONSHIP,
        MemoryType.LINK,
        MemoryType.FILE,
        MemoryType.IMAGE,
        MemoryType.AUDIO,
        MemoryType.MEETING,
    }.issubset(row_types)

    db_files = list(tmp_path.glob("*.db"))
    assert db_files == [db_path]
    assert blob_dir.exists()
