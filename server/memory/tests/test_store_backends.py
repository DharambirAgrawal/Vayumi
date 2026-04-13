from __future__ import annotations

from memory.stores.graph import GraphStore
from memory.stores.semantic import SemanticStore


def test_semantic_store_memory_backend_search_and_delete():
    store = SemanticStore(url="memory://", collection="t", embedding_model="sentence-transformers/all-MiniLM-L6-v2")

    for i in range(300):
        store.upsert(
            chunk_id=f"c{i}",
            text=f"priority task {i} for alice",
            metadata={"memory_id": f"m{i}", "speaker_id": "alice", "type": "fact"},
        )

    results = store.search("priority task alice", filter={"speaker_id": "alice"}, top_k=20)
    assert len(results) == 20

    deleted = store.delete(["c1", "c2", "c3"])
    assert deleted is True

    count = store.delete_by_memory_id("m4")
    assert isinstance(count, int)


def test_graph_store_date_filtering_and_relations():
    graph = GraphStore(uri="memory://", user="", password="")

    graph.add_entity("person:alice", "person", {"speaker_id": "alice", "name": "Alice"})
    graph.add_entity("meeting:old", "meeting", {"memory_id": "old", "date": "2026-01-12", "summary": "old meeting"})
    graph.add_entity("meeting:new", "meeting", {"memory_id": "new", "date": "2026-04-01", "summary": "new meeting"})
    graph.add_relationship("person:alice", "meeting:old", "PARTICIPATED_IN")
    graph.add_relationship("person:alice", "meeting:new", "PARTICIPATED_IN")

    meetings = graph.get_person_meetings("alice", date_from="2026-03-01", date_to="2026-04-30")
    assert meetings == ["new"]

    hits = graph.search("meeting", speaker_id="alice", date_from="2026-03-01", date_to="2026-04-30")
    assert hits
    assert all((h.get("memory_id") in {None, "new"}) for h in hits)
