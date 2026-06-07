from __future__ import annotations

from server.memory import facts
from server.memory.retrieval import RetrievalFilters, retrieve
from server.tools.registry import ToolResult


async def memory_recall(
    *,
    user_id: str,
    key: str | None = None,
    chain: bool = False,
    query: str | None = None,
    k: int = 5,
) -> ToolResult:
    key = (key or "").strip()
    query = (query or "").strip()

    if not key and not query:
        return ToolResult(
            status="error",
            summary="key or query is required",
            retryable=False,
        )

    if key:
        if chain:
            rows = await facts.get_chain(user_id, key)
            if not rows:
                payload: object = []
                summary = f"No history for key={key}"
            else:
                payload = [
                    {
                        "active": row.active,
                        "value": row.value,
                        "created_at": row.created_at.isoformat(),
                    }
                    for row in rows
                ]
                summary = f"Chain for {key} ({len(rows)} version(s))"
            return ToolResult(
                status="ok",
                summary=summary,
                data={"key": key, "chain": payload},
            )

        record = await facts.get_fact(user_id, key)
        if record is None:
            return ToolResult(
                status="ok",
                summary=f"No active fact for key={key}",
                data={"key": key, "value": None},
            )
        return ToolResult(
            status="ok",
            summary=f"Recalled {key}",
            data={"key": key, "value": record.value},
        )

    snippets = await retrieve(
        query,
        RetrievalFilters(user_id=user_id),
        k=max(1, min(k, 20)),
    )
    if not snippets:
        return ToolResult(
            status="ok",
            summary=f"No semantic matches for query={query!r}",
            data={"query": query, "snippets": []},
        )

    payload = [
        {
            "doc_id": snippet.doc_id,
            "key": snippet.key,
            "text": snippet.text,
            "score": snippet.score,
            "citation": snippet.citation,
        }
        for snippet in snippets
    ]
    return ToolResult(
        status="ok",
        summary=f"Found {len(snippets)} memory snippet(s) for {query!r}",
        data={"query": query, "snippets": payload},
    )
