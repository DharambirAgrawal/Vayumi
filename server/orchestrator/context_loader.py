from __future__ import annotations

from pathlib import Path

from .tools import get_tool_ids_with_skill_docs


def load_skill_docs(tool_ids: list[str]) -> str:
    root = Path(__file__).resolve().parent / "skills"
    docs: list[str] = []

    for tool_id in get_tool_ids_with_skill_docs(tool_ids):
        path = root / f"{tool_id}.md"
        if path.exists():
            docs.append(path.read_text(encoding="utf-8"))

    return "\n\n".join(docs).strip()
