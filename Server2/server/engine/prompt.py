from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

PROMPT_DIR = Path("prompts")
MAIN_PROMPT_PATH = PROMPT_DIR / "main.txt"


@dataclass(frozen=True)
class MainPromptContext:
    user_text: str
    warm_profile: str = ""
    history_lines: list[str] = field(default_factory=list)
    compressed_summary: str = ""
    recall_context: str = ""


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

    if context.recall_context.strip():
        sections.append(context.recall_context.strip())

    user_text = context.user_text.strip()
    sections.append(f"User: {user_text}\nVayumi:")
    return "\n\n".join(sections) + "\n"


@lru_cache(maxsize=16)
def _load_prompt(path: Path) -> str:
    return path.read_text(encoding="utf-8")
