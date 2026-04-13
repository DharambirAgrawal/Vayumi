from __future__ import annotations

import asyncio
import re
import sys
from pathlib import Path


def _ensure_repo_root() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    repo_root_str = str(repo_root)
    if repo_root_str not in sys.path:
        sys.path.append(repo_root_str)


def _classify(text: str) -> str:
    lower = text.lower()
    if any(token in lower for token in ["prefer", "i like", "i dislike", "please use", "don't use"]):
        return "preference"
    if any(token in lower for token in ["meeting", "deadline", "tomorrow", "next week", "at "]):
        return "event"
    if any(token in lower for token in ["manager", "reports to", "works with", "wife", "husband", "friend"]):
        return "relationship"
    return "fact"


def _extract_items(task_description: str, result: str, step_log: list[str]) -> list[str]:
    candidates = [task_description.strip(), result.strip()]
    for line in step_log[-10:]:
        cleaned = re.sub(r"\[.*?\]", "", line).strip()
        if cleaned:
            candidates.append(cleaned)
    unique: list[str] = []
    for candidate in candidates:
        if candidate and candidate not in unique and len(candidate.split()) >= 3:
            unique.append(candidate[:280])
    return unique[:5]


async def run_on_task(speaker_id: str, task_description: str, result: str, step_log: list[str]):
    await asyncio.to_thread(_save_items, speaker_id, _extract_items(task_description, result, step_log))


async def run_on_turns(speaker_id: str, turns: list[dict]):
    snippets: list[str] = []
    for turn in turns[-12:]:
        for chunk in turn.get("content", []):
            text = str(chunk.get("text", "")).strip()
            if text:
                snippets.append(text[:280])
    await asyncio.to_thread(_save_items, speaker_id, snippets[:8])


def _save_items(speaker_id: str, items: list[str]) -> None:
    if not items:
        return
    try:
        _ensure_repo_root()
        from memory import MemorySystem, MemoryType
    except Exception:
        return

    mem = MemorySystem(speaker_id=speaker_id)
    for item in items:
        try:
            mem.save(item, MemoryType(_classify(item)), speaker_id=speaker_id)
        except Exception:
            continue
