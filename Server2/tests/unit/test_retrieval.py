from __future__ import annotations

import tempfile
from collections.abc import Generator

import pytest

import server.db.lancedb as lancedb_mod
from server.memory.embeddings import embedding_dim
from server.memory.retrieval import RetrievalFilters, get_snippet_by_doc_id, retrieve


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
        {
            "fact_id": "f-food",
            "user_id": "u1",
            "key": "food.favorite",
            "value_text": "food.favorite: ramen",
            "embedding": _unit_vector(2),
        },
        {
            "fact_id": "f-other",
            "user_id": "u2",
            "key": "name",
            "value_text": "name: Bob",
            "embedding": _unit_vector(0),
        },
    ]
    db.create_table(lancedb_mod.FACTS_INDEX_TABLE, rows)
    monkeypatch.setattr(lancedb_mod, "_db", db)

    def fake_embed(text: str) -> list[float]:
        lowered = text.lower()
        if "paris" in lowered or "city" in lowered:
            return _unit_vector(1)
        if "ramen" in lowered or "food" in lowered:
            return _unit_vector(2)
        return _unit_vector(0)

    monkeypatch.setattr("server.memory.retrieval.embed_text", fake_embed)
    yield tmpdir
    monkeypatch.setattr(lancedb_mod, "_db", None)


@pytest.mark.asyncio
async def test_retrieve_returns_ranked_snippets_with_citations(
    seeded_facts_index: str,
) -> None:
    snippets = await retrieve(
        "what is my name",
        RetrievalFilters(user_id="u1"),
        k=2,
    )

    assert len(snippets) == 2
    assert snippets[0].doc_id == "f-name"
    assert snippets[0].key == "name"
    assert "Alex" in snippets[0].text
    assert snippets[0].citation == "doc:f-name key=name"
    assert snippets[0].score >= snippets[1].score
    assert snippets[1].doc_id == "f-city"


@pytest.mark.asyncio
async def test_retrieve_filters_by_user_id(seeded_facts_index: str) -> None:
    snippets = await retrieve(
        "name",
        RetrievalFilters(user_id="u2"),
        k=5,
    )

    assert len(snippets) == 1
    assert snippets[0].doc_id == "f-other"
    assert "Bob" in snippets[0].text


@pytest.mark.asyncio
async def test_get_snippet_by_doc_id(seeded_facts_index: str) -> None:
    snippet = await get_snippet_by_doc_id("u1", "f-food")
    assert snippet is not None
    assert snippet.doc_id == "f-food"
    assert snippet.key == "food.favorite"
    assert "ramen" in snippet.text
    assert snippet.citation == "doc:f-food key=food.favorite"


@pytest.mark.asyncio
async def test_get_snippet_by_doc_id_wrong_user_returns_none(
    seeded_facts_index: str,
) -> None:
    snippet = await get_snippet_by_doc_id("u2", "f-name")
    assert snippet is None
