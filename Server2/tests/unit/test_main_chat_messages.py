from __future__ import annotations

from server.engine.prompt import (
    MainPromptContext,
    build_main_chat_messages,
    today_context_line,
)


def test_system_message_is_static_prompt_only() -> None:
    messages = build_main_chat_messages(
        MainPromptContext(
            user_text="hey",
            warm_profile="Known profile facts:\n- name: Alex",
            task_board_block="active_tasks: none",
            recall_context="Do not use tools in this reply.",
            history_lines=["user: hi", "assistant: hello"],
        )
    )

    assert messages[0]["role"] == "system"
    assert "You are Vayumi" in messages[0]["content"]
    assert "Alex" not in messages[0]["content"]
    assert "active_tasks" not in messages[0]["content"]
    assert "Do not use tools" not in messages[0]["content"]
    assert messages[-1] == {"role": "user", "content": "hey"}


def test_session_context_includes_today_date() -> None:
    line = today_context_line()
    assert "Today's date (server):" in line
    assert "web_search" in line

    messages = build_main_chat_messages(MainPromptContext(user_text="hey"))
    assert "Today's date (server):" in messages[1]["content"]


def test_session_context_is_separate_from_user_message() -> None:
    messages = build_main_chat_messages(
        MainPromptContext(
            user_text="hey",
            warm_profile="Known profile facts:\n- name: Alex",
        )
    )

    assert messages[1]["role"] == "user"
    assert "Session context" in messages[1]["content"]
    assert "Alex" in messages[1]["content"]
    assert "hey" not in messages[1]["content"]
    assert messages[2] == {"role": "assistant", "content": "Understood."}
    assert messages[-1] == {"role": "user", "content": "hey"}
