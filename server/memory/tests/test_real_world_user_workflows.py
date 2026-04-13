from __future__ import annotations

from datetime import datetime, timedelta

from memory import MemorySystem, MemoryType
from memory.short_term import ShortTermBuffer


def test_real_user_small_to_large_create_and_query_quality(tmp_path):
    mem = MemorySystem(
        speaker_id="nina",
        db_path=str(tmp_path / "real-create.db"),
        blob_dir=str(tmp_path / "blobs"),
        qdrant_url="memory://",
        provider_mode="local",
    )

    # Small, medium, and large realistic memories from normal user activity.
    small = "I prefer concise standup updates."
    medium = (
        "Sprint planning recap: frontend migration starts Monday, QA validation starts Wednesday, "
        "and release candidate freeze is Friday at 4 PM."
    )
    large = " ".join(
        [
            "Q2 roadmap item: billing reliability improvement with retry envelopes and idempotent writes.",
            "Cross-team dependency: analytics schema stabilization and dashboard migration.",
            "Risk noted: legacy webhook retries can double-count events unless deduplicated.",
        ]
        * 60
    )

    mem.save(small, MemoryType.PREFERENCE)
    mem.save(medium, MemoryType.EVENT)
    mem.save(large, MemoryType.FACT)

    result = mem.search("billing reliability idempotent writes", top_k=5)
    assert result.results
    assert any("billing reliability" in r.content.lower() for r in result.results)

    # Context must remain bounded/readable even with large source memories.
    assert len(result.context) < 9000


def test_real_user_small_to_big_update_and_regression_search(tmp_path):
    mem = MemorySystem(
        speaker_id="nina",
        db_path=str(tmp_path / "real-update.db"),
        blob_dir=str(tmp_path / "blobs"),
        qdrant_url="memory://",
        provider_mode="local",
    )

    created = mem.save("My name is Nena", MemoryType.FACT)
    memory_id = str(created["memory_id"])

    # Small corrective update.
    update1 = mem.update(memory_id, "My name is Nina", speaker_id="nina")
    assert update1["success"] is True

    # Large profile update akin to real account/profile enrichment.
    expanded = (
        "My name is Nina. I lead platform QA for payments, auth, and notifications. "
        "I prefer concise summaries first, then detailed risk breakdowns with ownership and dates. "
        "I track incidents weekly and prioritize rollback safety, observability, and release gates."
    )
    update2 = mem.update(memory_id, expanded, speaker_id="nina")
    assert update2["success"] is True

    hit = mem.search("who leads platform QA", top_k=3)
    assert hit.results
    assert any("nina" in r.content.lower() and "platform qa" in r.content.lower() for r in hit.results)


def test_real_user_small_and_bulk_delete_integrity(tmp_path):
    mem = MemorySystem(
        speaker_id="omar",
        db_path=str(tmp_path / "real-delete.db"),
        blob_dir=str(tmp_path / "blobs"),
        qdrant_url="memory://",
        provider_mode="local",
    )

    # Create mixed records and links.
    created_ids = []
    for i in range(5):
        res = mem.save(f"Omar preference note {i}", MemoryType.PREFERENCE)
        created_ids.append(str(res["memory_id"]))

    mem.link_ingester.fetch = lambda url: f"notes for {url}"  # type: ignore[method-assign]
    mem.link_ingester.fetch_github = lambda url: f"repo notes for {url}"  # type: ignore[method-assign]

    mem.ingest("link", "https://github.com/acme/repo", speaker_id="omar")
    mem.ingest("link", "https://github.com/acme/repo2", speaker_id="omar")
    mem.ingest("link", "https://example.com/product-update", speaker_id="omar")

    # Small delete.
    one = mem.delete(created_ids[0], speaker_id="omar")
    assert one["success"] is True

    # Bulk delete by domain then all remaining links.
    github_del = mem.delete_links(speaker_id="omar", domain="github.com")
    assert github_del["success"] is True
    assert github_del["deleted_count"] == 2

    all_links_del = mem.delete_links(speaker_id="omar", delete_all=True)
    assert all_links_del["success"] is True
    assert all_links_del["deleted_count"] >= 1


def test_short_term_buffer_under_heavy_turns_keeps_recent_context():
    buf = ShortTermBuffer(max_tokens=45)

    for i in range(80):
        buf.add("user", f"Turn {i}: status update with enough words to consume tokens quickly")

    turns = buf.get_turns()
    assert turns
    assert buf.token_count() <= 45

    # Old turns should have been dropped; most recent one must remain.
    snapshot = buf.to_text().lower()
    assert "turn 79" in snapshot
    assert "turn 0" not in snapshot


def test_large_semantic_dataset_returns_meaningful_top_k(tmp_path):
    mem = MemorySystem(
        speaker_id="lina",
        db_path=str(tmp_path / "real-semantic.db"),
        blob_dir=str(tmp_path / "blobs"),
        qdrant_url="memory://",
        provider_mode="local",
    )

    # Background noise from generic memories.
    for i in range(400):
        mem.save(
            f"General team chatter entry {i} about routine syncs and lightweight project updates.",
            MemoryType.EVENT,
        )

    # Highly relevant target memories.
    for i in range(18):
        mem.save(
            (
                f"Incident RCA {i}: payment webhook duplicate delivery. "
                "Fix uses idempotency keys, dedupe table, and retry-jitter policy."
            ),
            MemoryType.FACT,
        )

    found = mem.search("payment webhook duplicate idempotency dedupe", top_k=10)
    assert len(found.results) == 10

    # Expect majority of top-k to be genuinely relevant to query intent.
    relevant = [
        r
        for r in found.results
        if ("idempot" in r.content.lower() or "webhook" in r.content.lower() or "dedupe" in r.content.lower())
    ]
    assert len(relevant) >= 7


def test_date_filtered_retrieval_real_timeline(tmp_path):
    mem = MemorySystem(
        speaker_id="mira",
        db_path=str(tmp_path / "real-dates.db"),
        blob_dir=str(tmp_path / "blobs"),
        qdrant_url="memory://",
        provider_mode="local",
    )

    now = datetime.utcnow()
    old_date = (now - timedelta(days=50)).date().isoformat()
    new_date = (now - timedelta(days=2)).date().isoformat()

    mem.save("Old incident note for archives", MemoryType.EVENT, expires_at=old_date)
    recent = mem.save("Recent incident follow-up and owner assignment", MemoryType.EVENT, expires_at=new_date)

    # Enforce created_at date filter via explicit store mutation for deterministic test dates.
    recent_id = str(recent["memory_id"])
    rec = mem.explicit.get(recent_id)
    assert rec is not None
    mem.explicit.update(recent_id, {"created_at": new_date + "T12:00:00"})

    rows = mem.explicit.filter(speaker_id="mira", date_from=(now - timedelta(days=7)).date().isoformat(), limit=20)
    assert rows
    assert all(r.created_at.date().isoformat() >= (now - timedelta(days=7)).date().isoformat() for r in rows)