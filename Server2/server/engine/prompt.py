from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from server.subagents.capabilities.bundle import CapabilityBundle

PROMPT_DIR = Path("prompts")
MAIN_PROMPT_PATH = PROMPT_DIR / "main.txt"
GREETING_PROMPT_PATH = PROMPT_DIR / "greeting.txt"
ACK_PROMPT_PATH = PROMPT_DIR / "ack.txt"
SUB_PROMPT_DIR = PROMPT_DIR / "sub"


@dataclass(frozen=True)
class MainPromptContext:
    user_text: str
    warm_profile: str = ""
    history_lines: list[str] = field(default_factory=list)
    compressed_summary: str = ""
    recall_context: str = ""  # recall blocks, tool results, and other injected context
    task_board_block: str = ""


@dataclass(frozen=True)
class SubPromptContext:
    capability: str
    task_id: str
    goal: str
    payload: dict
    warm_profile: str = ""
    transcript_lines: list[str] = field(default_factory=list)
    tool_context: str = ""


def build_greeting_prompt(*, user_text: str) -> str:
    system_prompt = _load_prompt(GREETING_PROMPT_PATH).strip()
    return f"{system_prompt}\n\nUser: {user_text.strip()}\nVayumi:\n"


def build_ack_prompt(*, user_text: str, warm_profile: str = "") -> str:
    system_prompt = _load_prompt(ACK_PROMPT_PATH).strip()
    sections = [system_prompt]
    if warm_profile.strip():
        sections.append(warm_profile.strip())
    sections.append(f"User: {user_text.strip()}\nVayumi:")
    return "\n\n".join(sections)


def today_context_line() -> str:
    """Server date for the model — training weights are not real-time."""
    today = date.today()
    return (
        f"Today's date (server): {today.isoformat()} ({today.strftime('%A')}). "
        "You do not have live internet knowledge in your weights. "
        "For anything current, recent, or after your training cutoff, use web_search "
        "or say you need to look it up — never state dates, prices, or news from memory."
    )


def _session_context_parts(context: MainPromptContext) -> list[str]:
    parts: list[str] = [today_context_line()]
    if context.warm_profile.strip():
        parts.append(context.warm_profile.strip())
    if context.compressed_summary.strip():
        parts.append(f"Earlier conversation summary:\n{context.compressed_summary.strip()}")
    if context.task_board_block.strip():
        parts.append(context.task_board_block.strip())
    if context.recall_context.strip():
        parts.append(context.recall_context.strip())
    return parts


def _append_chat_message(
    messages: list[dict[str, str]],
    *,
    role: str,
    content: str,
) -> None:
    if messages and messages[-1]["role"] == role:
        messages[-1] = {
            "role": role,
            "content": messages[-1]["content"] + "\n" + content,
        }
    else:
        messages.append({"role": role, "content": content})


def build_main_prompt(context: MainPromptContext) -> str:
    system_prompt = _load_prompt(MAIN_PROMPT_PATH).strip()
    sections: list[str] = [system_prompt]

    context_parts = _session_context_parts(context)
    if context_parts:
        sections.append(
            "Session context (not the user's message):\n"
            + "\n\n".join(context_parts)
        )

    if context.history_lines:
        history_block = "\n".join(context.history_lines)
        sections.append(f"Recent conversation:\n{history_block}")

    user_text = context.user_text.strip()
    sections.append(f"User: {user_text}\nVayumi:")
    return "\n\n".join(sections) + "\n"


def build_main_chat_messages(context: MainPromptContext) -> list[dict[str, str]]:
    """Build OpenAI-style messages for llama-server /v1/chat/completions.

    Static rules live in ``system``. Session context, tool results, and runtime
    instructions live in a separate user/assistant pair so they are not mixed
    with the user's latest message.
    """
    system_prompt = _load_prompt(MAIN_PROMPT_PATH).strip()
    messages: list[dict[str, str]] = [{"role": "system", "content": system_prompt}]

    context_parts = _session_context_parts(context)
    if context_parts:
        _append_chat_message(
            messages,
            role="user",
            content=(
                "Session context (not the user's latest message):\n\n"
                + "\n\n".join(context_parts)
            ),
        )
        _append_chat_message(messages, role="assistant", content="Understood.")

    for line in context.history_lines:
        if line.startswith("user: "):
            role, content = "user", line[6:]
        elif line.startswith("assistant: "):
            role, content = "assistant", line[11:]
        else:
            role, content = "user", line
        _append_chat_message(messages, role=role, content=content)

    user_text = context.user_text.strip()
    if messages and messages[-1]["role"] == "user":
        if messages[-1]["content"] != user_text:
            _append_chat_message(messages, role="user", content=user_text)
    else:
        _append_chat_message(messages, role="user", content=user_text)

    return messages


def build_subagent_prompt(
    bundle: CapabilityBundle,
    context: SubPromptContext,
) -> str:
    """Assemble a sub-agent prompt from capability bundle + task context."""
    system_prompt = _load_prompt(bundle.prompt_path).strip()
    sections: list[str] = [
        system_prompt,
        f"Task id: {context.task_id}",
        f"Capability: {bundle.name}",
        f"Goal: {context.goal.strip()}",
    ]
    if context.warm_profile.strip():
        sections.append(context.warm_profile.strip())
    if context.payload:
        sections.append(f"Payload: {json.dumps(context.payload, ensure_ascii=False)}")
    if context.tool_context.strip():
        sections.append(context.tool_context.strip())
    if context.transcript_lines:
        sections.append("Transcript:\n" + "\n".join(context.transcript_lines))
    sections.append("Worker:")
    return "\n\n".join(sections) + "\n"


def build_subagent_chat_messages(
    bundle: CapabilityBundle,
    context: SubPromptContext,
) -> list[dict[str, str]]:
    system_prompt = _load_prompt(bundle.prompt_path).strip()
    sections: list[str] = [
        system_prompt,
        f"Task id: {context.task_id}",
        f"Capability: {bundle.name}",
        f"Goal: {context.goal.strip()}",
    ]
    if context.warm_profile.strip():
        sections.append(context.warm_profile.strip())
    if context.payload:
        sections.append(f"Payload: {json.dumps(context.payload, ensure_ascii=False)}")
    if context.tool_context.strip():
        sections.append(context.tool_context.strip())

    messages: list[dict[str, str]] = [{"role": "system", "content": "\n\n".join(sections)}]

    for line in context.transcript_lines:
        if line.startswith("assistant: "):
            role, content = "assistant", line[11:]
        elif line.startswith("user: "):
            role, content = "user", line[6:]
        elif line.startswith("system: "):
            # Tool results injected as user-side context
            role, content = "user", line[8:]
        else:
            role, content = "user", line

        if messages and messages[-1]["role"] == role:
            # Merge consecutive same-role messages — Gemma requires strict alternation
            messages[-1] = {"role": role, "content": messages[-1]["content"] + "\n" + content}
        else:
            messages.append({"role": role, "content": content})

    if not context.transcript_lines:
        messages.append({"role": "user", "content": "Begin task."})

    return messages



def build_sub_prompt(context: SubPromptContext) -> str:
    """Legacy entry: load bundle by name and build prompt (tests / simple callers)."""
    from server.subagents.capabilities import load_capability

    bundle = load_capability(context.capability)
    return build_subagent_prompt(bundle, context)


SUMMARIZER_PROMPT_PATH = PROMPT_DIR / "summarizer.txt"
MEETING_SUMMARY_PROMPT_PATH = PROMPT_DIR / "meeting_summary.txt"


@dataclass(frozen=True)
class SummarizerPromptContext:
    existing_summary: str
    turn_lines: list[str]


def build_summarizer_chat_messages(
    context: SummarizerPromptContext,
) -> list[dict[str, str]]:
    system_prompt = _load_prompt(SUMMARIZER_PROMPT_PATH).strip()
    parts: list[str] = []
    if context.existing_summary.strip():
        parts.append(
            "Existing compressed summary:\n" + context.existing_summary.strip()
        )
    if context.turn_lines:
        parts.append(
            "Conversation turns to compress:\n" + "\n".join(context.turn_lines)
        )
    user_block = "\n\n".join(parts) if parts else "No turns to compress."
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_block},
    ]


@dataclass(frozen=True)
class MeetingSummaryPromptContext:
    transcript_lines: list[str]


def build_meeting_summary_chat_messages(
    context: MeetingSummaryPromptContext,
) -> list[dict[str, str]]:
    system_prompt = _load_prompt(MEETING_SUMMARY_PROMPT_PATH).strip()
    transcript = "\n\n".join(context.transcript_lines)
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": f"Meeting transcript:\n\n{transcript}"},
    ]


@lru_cache(maxsize=16)
def _load_prompt(path: Path) -> str:
    return path.read_text(encoding="utf-8")
