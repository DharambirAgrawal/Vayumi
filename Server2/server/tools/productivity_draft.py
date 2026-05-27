from __future__ import annotations

from server.tools.registry import ToolResult


async def draft_document(
    *,
    user_id: str,
    title: str = "",
    instructions: str = "",
) -> ToolResult:
    del user_id, title, instructions
    return ToolResult(
        status="user_action_required",
        summary=(
            "Workspace integrations (Notion, Drive, GitHub) are not connected yet. "
            "Use research summarize_url on a public link, or paste text in the goal."
        ),
        data={"integration": "productivity", "action": "connect_workspace"},
        safe_to_show_user=True,
    )
