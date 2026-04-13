from __future__ import annotations

import base64

from memory import MemorySystem, MemoryType


def test_heavy_multi_user_save_search_update_delete(tmp_path):
    db_path = tmp_path / "memory.db"
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

    alice_ids = []
    bob_ids = []

    for i in range(220):
        res = alice.save(f"Alice project preference {i}", MemoryType.PREFERENCE)
        alice_ids.append(res["memory_id"])
    for i in range(180):
        res = bob.save(f"Bob workload event {i}", MemoryType.EVENT)
        bob_ids.append(res["memory_id"])

    alice_search = alice.search("project preference", top_k=10)
    assert alice_search.results
    assert all(r.speaker_id == "alice" for r in alice_search.results)

    bob_search = bob.search("workload event", top_k=10)
    assert bob_search.results
    assert all(r.speaker_id == "bob" for r in bob_search.results)

    target = alice_ids[0]
    updated = alice.update(target, "Alice moved to a new role", speaker_id="alice")
    assert updated["success"] is True

    post_update = alice.search("new role", top_k=5)
    assert any("new role" in r.content.lower() for r in post_update.results)

    forbidden_delete = bob.delete(target, speaker_id="bob")
    assert forbidden_delete["success"] is False

    ok_delete = alice.delete(target, speaker_id="alice")
    assert ok_delete["success"] is True


def test_ingest_paths_with_varied_inputs(tmp_path):
    mem = MemorySystem(
        speaker_id="carol",
        db_path=str(tmp_path / "ingest.db"),
        blob_dir=str(tmp_path / "blobs"),
        qdrant_url="memory://",
        provider_mode="local",
    )

    file_payload = base64.b64encode(b"name,role\nMaya,Design Lead\n").decode("ascii")
    image_payload = base64.b64encode(b"\x89PNG\r\n\x1a\n").decode("ascii")
    audio_payload = base64.b64encode(b"not-really-audio-but-bytes" * 128).decode("ascii")

    file_ing = mem.ingest("file", file_payload, title="team")
    image_ing = mem.ingest("image", image_payload, title="mock-img")
    audio_ing = mem.ingest("audio", audio_payload, title="mock-audio")
    meeting_ing = mem.ingest("meeting", "[carol 0] action: send recap", participants=["carol"])

    assert file_ing.success and file_ing.chunk_count >= 1
    assert image_ing.success and image_ing.chunk_count >= 1
    assert audio_ing.success and audio_ing.chunk_count >= 1
    assert meeting_ing.success and meeting_ing.chunk_count >= 1
