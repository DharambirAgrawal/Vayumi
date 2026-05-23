from __future__ import annotations

from server.tools.registry import ToolResult


async def read_email(
    *,
    user_id: str,
    query: str = "",
    max_results: int = 10,
) -> ToolResult:
    del user_id, query, max_results
    return ToolResult(
        status="user_action_required",
        summary=(
            "Email is not connected for this user. "
            "Complete Gmail OAuth via Server 1, then retry."
        ),
        data={"integration": "gmail", "action": "oauth_connect"},
        safe_to_show_user=True,
    )


async def send_email(
    *,
    user_id: str,
    to: str,
    subject: str,
    body: str,
) -> ToolResult:
    del user_id, to, subject, body
    return ToolResult(
        status="user_action_required",
        summary=(
            "Outbound email requires a connected mailbox. "
            "Link Gmail via Server 1 before sending."
        ),
        data={"integration": "gmail", "action": "oauth_connect"},
        safe_to_show_user=True,
    )
