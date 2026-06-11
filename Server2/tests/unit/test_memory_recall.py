from __future__ import annotations

import tempfile
from collections.abc import Generator

import pytest

import server.db.lancedb as lancedb_mod
from server.memory.embeddings import embedding_dim
from server.tools.memory_recall import memory_recall


def _unit_vector(index: int) -> list[float]:
    dim = embedding_dim()
    vector = [0.0] * dim
    vector[index % dim] = 1.0
    return vector


@pytest.fixture
def seeded_facts_index(monkeypatch: pytest.MonkeyPatch) -> Generator[str, None, None]:
    tmpdir = tempfile.mkdtemp()
    db = lancedb_mod.lancedb.connect(tmpdir)
    rows = [
        {
            "fact_id": "f-name",
            "user_id": "u1",
            "key": "name",
            "value_text": "name: Alex",
            "embedding": _unit_vector(0),
        },
        {
            "fact_id": "f-city",
            "user_id": "u1",
            "key": "city",
            "value_text": "city: Paris",
            "embedding": _unit_vector(1),
        },
    ]
    db.create_table(lancedb_mod.FACTS_INDEX_TABLE, rows)
    monkeypatch.setattr(lancedb_mod, "_db", db)
    monkeypatch.setattr(
        "server.memory.retrieval.embed_text",
        lambda text: _unit_vector(1 if "paris" in text.lower() else 0),
    )
    yield tmpdir
    monkeypatch.setattr(lancedb_mod, "_db", None)


@pytest.mark.asyncio
async def test_memory_recall_semantic_query_returns_snippets(
    seeded_facts_index: str,
) -> None:
    result = await memory_recall(user_id="u1", query="what city is Paris")

    assert result.status == "ok"
    assert result.data is not None
    snippets = result.data["snippets"]
    assert len(snippets) == 2
    assert snippets[0]["doc_id"] == "f-city"
    assert snippets[0]["citation"] == "doc:f-city key=city"
    assert "Paris" in snippets[0]["text"]


@pytest.mark.asyncio
async def test_memory_recall_requires_key_or_query() -> None:
    result = await memory_recall(user_id="u1")
    assert result.status == "error"
    assert "required" in result.summary.lower()
