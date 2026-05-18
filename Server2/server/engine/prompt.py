from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

PROMPT_DIR = Path("prompts")
MAIN_PROMPT_PATH = PROMPT_DIR / "main.txt"


@dataclass(frozen=True)
class MainPromptContext:
    user_text: str


def build_main_prompt(context: MainPromptContext) -> str:
    system_prompt = _load_prompt(MAIN_PROMPT_PATH).strip()
    user_text = context.user_text.strip()
    return (
        f"{system_prompt}\n\n"
        "Conversation:\n"
        f"User: {user_text}\n"
        "Vayumi:"
    )


@lru_cache(maxsize=16)
def _load_prompt(path: Path) -> str:
    return path.read_text(encoding="utf-8")
