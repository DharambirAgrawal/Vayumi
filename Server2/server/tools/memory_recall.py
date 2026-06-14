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
    meeting_id: str | None = None,
    k: int = 5,
) -> ToolResult:
    key = (key or "").strip()
    query = (query or "").strip()
    meeting_id = (meeting_id or "").strip()

    if not key and not query and not meeting_id:
        return ToolResult(
            status="error",
            summary="key, query, or meeting_id is required",
            retryable=False,
        )

    if meeting_id:
        from server.memory.retrieval import get_meeting_recall

        payload = await get_meeting_recall(user_id, meeting_id)
        return ToolResult(
            status="ok",
            summary=f"Recalled meeting {meeting_id}",
            data={"meeting_id": meeting_id, "text": payload},
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
