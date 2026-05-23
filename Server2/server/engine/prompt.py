from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

PROMPT_DIR = Path("prompts")
MAIN_PROMPT_PATH = PROMPT_DIR / "main.txt"
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


def build_ack_prompt(*, user_text: str, warm_profile: str = "") -> str:
    system_prompt = _load_prompt(ACK_PROMPT_PATH).strip()
    sections = [system_prompt]
    if warm_profile.strip():
        sections.append(warm_profile.strip())
    sections.append(f"User: {user_text.strip()}\nVayumi:")
    return "\n\n".join(sections)


def build_main_prompt(context: MainPromptContext) -> str:
    system_prompt = _load_prompt(MAIN_PROMPT_PATH).strip()
    sections: list[str] = [system_prompt]

    if context.warm_profile.strip():
        sections.append(context.warm_profile.strip())

    if context.compressed_summary.strip():
        sections.append(f"Earlier conversation summary:\n{context.compressed_summary.strip()}")

    if context.history_lines:
        history_block = "\n".join(context.history_lines)
        sections.append(f"Recent conversation:\n{history_block}")

    if context.task_board_block.strip():
        sections.append(context.task_board_block.strip())

    if context.recall_context.strip():
        sections.append(context.recall_context.strip())

    user_text = context.user_text.strip()
    sections.append(f"User: {user_text}\nVayumi:")
    return "\n\n".join(sections) + "\n"


def build_sub_prompt(context: SubPromptContext) -> str:
    path = SUB_PROMPT_DIR / f"{context.capability}.txt"
    if not path.is_file():
        path = SUB_PROMPT_DIR / "research.txt"
    system_prompt = _load_prompt(path).strip()
    sections: list[str] = [
        system_prompt,
        f"Task id: {context.task_id}",
        f"Goal: {context.goal.strip()}",
    ]
    if context.warm_profile.strip():
        sections.append(context.warm_profile.strip())
    if context.payload:
        sections.append(f"Payload: {json.dumps(context.payload, ensure_ascii=False)}")
    if context.transcript_lines:
        sections.append("Transcript:\n" + "\n".join(context.transcript_lines))
    if context.tool_context.strip():
        sections.append(context.tool_context.strip())
    sections.append("Worker:")
    return "\n\n".join(sections) + "\n"


@lru_cache(maxsize=16)
def _load_prompt(path: Path) -> str:
    return path.read_text(encoding="utf-8")
