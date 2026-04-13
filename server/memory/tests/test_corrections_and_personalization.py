from __future__ import annotations

from memory import MemorySystem, MemoryType
from memory.models import MemoryRecord


def test_update_by_query_for_wrong_name(tmp_path):
    mem = MemorySystem(
        speaker_id="alex",
        db_path=str(tmp_path / "corr.db"),
        blob_dir=str(tmp_path / "blobs"),
        qdrant_url="memory://",
        provider_mode="local",
    )

    saved = mem.save("My manager name is Jhon", MemoryType.FACT)
    assert saved["success"] is True

    result = mem.update_by_query(
        query="manager name is Jhon",
        new_content="My manager name is John",
        speaker_id="alex",
    )
    assert result["success"] is True

    lookup = mem.search("manager name is John", top_k=5)
    assert any("John" in r.content for r in lookup.results)


def test_delete_links_bulk_by_domain_and_all(tmp_path):
    mem = MemorySystem(
        speaker_id="sam",
        db_path=str(tmp_path / "links.db"),
        blob_dir=str(tmp_path / "blobs"),
        qdrant_url="memory://",
        provider_mode="local",
    )

    mem.link_ingester.fetch = lambda url: f"content for {url}"  # type: ignore[method-assign]
    mem.link_ingester.fetch_github = lambda url: f"github content for {url}"  # type: ignore[method-assign]

    mem.ingest("link", "https://github.com/org/repo", speaker_id="sam")
    mem.ingest("link", "https://news.ycombinator.com", speaker_id="sam")
    mem.ingest("link", "https://github.com/org/repo2", speaker_id="sam")

    d1 = mem.delete_links(speaker_id="sam", domain="github.com")
    assert d1["success"] is True
    assert d1["deleted_count"] == 2

    d2 = mem.delete_links(speaker_id="sam", delete_all=True)
    assert d2["success"] is True
    assert d2["deleted_count"] >= 1


def test_personalization_emotion_history_over_sessions(tmp_path):
    mem = MemorySystem(
        speaker_id="maya",
        db_path=str(tmp_path / "pers.db"),
        blob_dir=str(tmp_path / "blobs"),
        qdrant_url="memory://",
        provider_mode="local",
    )

    mem.add_turn("maya", "I am stressed and overwhelmed today, urgent issues everywhere")
    mem.add_turn("maya", "Need concise updates")
    mem.flush_session()

    m1 = mem.get_user_model("maya")
    assert len(m1.emotional_history) >= 1

    mem.add_turn("maya", "Great progress today, happy with the results")
    mem.add_turn("maya", "awesome collaboration with team")
    mem.flush_session()

    m2 = mem.get_user_model("maya")
    assert len(m2.emotional_history) >= 2
    assert m2.emotional_patterns in {"generally positive", "stable", "under sustained pressure", "often terse under pressure"}


def test_update_propagates_to_graph_node(tmp_path):
    mem = MemorySystem(
        speaker_id="ravi",
        db_path=str(tmp_path / "graph.db"),
        blob_dir=str(tmp_path / "blobs"),
        qdrant_url="memory://",
        provider_mode="local",
    )

    mem.link_ingester.fetch = lambda url: f"initial summary for {url}"  # type: ignore[method-assign]
    ing = mem.ingest("link", "https://example.com", speaker_id="ravi", title="Example")

    rec = mem.explicit.get(ing.memory_id)
    assert rec is not None and rec.graph_node_id

    upd = mem.update(ing.memory_id, "updated summary for link", speaker_id="ravi")
    assert upd["success"] is True

    node = mem.graph.get_entity(rec.graph_node_id)
    assert "updated summary" in str(node.get("summary", ""))
