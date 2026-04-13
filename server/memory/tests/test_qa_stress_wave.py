from __future__ import annotations

import base64
from concurrent.futures import ThreadPoolExecutor

import pytest

from memory import MemorySystem, MemoryType
from memory.errors import MemoryValidationError


def test_invalid_base64_payload_rejected_for_non_link_ingest(tmp_path):
    mem = MemorySystem(
        speaker_id="qa",
        db_path=str(tmp_path / "invalid-b64.db"),
        blob_dir=str(tmp_path / "blobs"),
        qdrant_url="memory://",
        provider_mode="local",
    )

    with pytest.raises(MemoryValidationError):
        mem.ingest("image", "!!!not-base64!!!")


def test_binary_ingesters_store_memory_id_on_semantic_chunks(tmp_path):
    mem = MemorySystem(
        speaker_id="qa",
        db_path=str(tmp_path / "binary-index.db"),
        blob_dir=str(tmp_path / "blobs"),
        qdrant_url="memory://",
        provider_mode="local",
    )

    file_payload = base64.b64encode(b"alpha beta gamma").decode("ascii")
    image_payload = base64.b64encode(b"\x89PNG\r\n\x1a\n").decode("ascii")
    audio_payload = base64.b64encode(b"audio-bytes" * 64).decode("ascii")

    ingested = [
        mem.ingest("file", file_payload, title="file-a"),
        mem.ingest("image", image_payload, title="img-a"),
        mem.ingest("audio", audio_payload, title="aud-a"),
    ]

    for row in ingested:
        rec = mem.explicit.get(row.memory_id)
        assert rec is not None
        assert rec.chunk_ids
        for chunk_id in rec.chunk_ids:
            md = mem.semantic._items[chunk_id]["metadata"]  # in-memory semantic backend during tests
            assert md.get("memory_id") == row.memory_id


def test_meeting_chunks_are_searchable_with_speaker_filter(tmp_path):
    mem = MemorySystem(
        speaker_id="alice",
        db_path=str(tmp_path / "meeting-index.db"),
        blob_dir=str(tmp_path / "blobs"),
        qdrant_url="memory://",
        provider_mode="local",
    )

    mem.ingest(
        "meeting",
        "[alice 0] action: draft release notes\n[bob 10] follow up with infra",
        participants=["alice", "bob"],
    )

    scoped_hits = mem.semantic.search("release notes", filter={"speaker_id": "alice"}, top_k=5)
    assert scoped_hits, "meeting chunks should be retrievable under speaker-scoped semantic filtering"


def test_concurrent_writes_and_reads_do_not_cross_speakers(tmp_path):
    db_path = tmp_path / "concurrency.db"
    blob_dir = tmp_path / "blobs"

    alice = MemorySystem(
        speaker_id="alice",
        db_path=str(db_path),
        blob_dir=str(blob_dir),
        qdrant_url="memory://",
        provider_mode="local",
    )
    bob = MemorySystem(
        speaker_id="bob",
        db_path=str(db_path),
        blob_dir=str(blob_dir),
        qdrant_url="memory://",
        provider_mode="local",
    )

    def save_for(mem: MemorySystem, speaker: str, total: int):
        for i in range(total):
            mem.save(f"{speaker} concurrent item {i}", MemoryType.FACT)

    with ThreadPoolExecutor(max_workers=4) as pool:
        f1 = pool.submit(save_for, alice, "alice", 140)
        f2 = pool.submit(save_for, bob, "bob", 140)
        f1.result()
        f2.result()

    alice_hits = alice.search("concurrent item", top_k=25)
    bob_hits = bob.search("concurrent item", top_k=25)

    assert alice_hits.results
    assert bob_hits.results
    assert all(hit.speaker_id == "alice" for hit in alice_hits.results)
    assert all(hit.speaker_id == "bob" for hit in bob_hits.results)