from __future__ import annotations

import json

from .constants import TaskSignal
from .capability_router import CAPABILITY_MENU
from .history_store import history_store
from .tools import get_schemas_for_main_llm, get_schemas_for_task
from .sub_agent import REPORT_SCHEMA


def build_main_developer_prompt(speaker_id: str, user_profile: str) -> str:
    return (
        "You are a helpful personalized assistant.\n\n"
        f"[SESSION]\nSpeaker: {speaker_id}\n\n"
        f"[USER PROFILE]\n{user_profile or 'No profile available.'}\n\n"
        "[YOUR DIRECT TOOLS]\n"
        "Call these for instant, single-step tasks.\n"
        "Format: <start_function_call>call:name{key:value}<end_function_call>\n"
        f"{json.dumps(get_schemas_for_main_llm(), indent=2)}\n\n"
        f"{CAPABILITY_MENU}\n"
        "[DIRECTIVES]\n"
        "For multi-step tasks, write directive blocks parsed by the system.\n"
        "Start task:\n[DELEGATE]\ntask: <self-contained task>\ncapability: <name1,name2>\n\n"
        "Cancel task:\n[STOP]\ntask_id: <id>\n\n"
        "Resume paused task:\n[ANSWER_TO]\ntask_id: <id>\nanswer: <user answer>\n\n"
        "Switch mode:\n[MODE_SWITCH]\nmode: <conversation or meeting>\n"
    )


def build_turn_context(
    mem_context: str,
    active_tasks: str,
    pending_results: list[dict],
    vayumi_state: dict,
    meeting_transcript: str | None,
) -> dict:
    parts: list[str] = []

    if mem_context:
        parts.append(f"[MEMORY]\n{mem_context}")
    if active_tasks:
        parts.append(active_tasks)
    if pending_results:
        lines = []
        for item in pending_results:
            tag = "completed" if item.get("type") == TaskSignal.DONE else "failed"
            lines.append(f'Task "{item.get("description", "task")}" {tag}: {item.get("message", "")}')
        parts.append("[TASK RESULTS THIS TURN]\n" + "\n".join(lines))
    if vayumi_state:
        parts.append(
            "[SESSION STATE]\n"
            f"mode: {vayumi_state.get('mode', 'conversation')}\n"
            f"is_ai_speaking: {vayumi_state.get('is_ai_speaking', False)}"
        )
    if meeting_transcript:
        parts.append(f"[MEETING TRANSCRIPT - current session]\n{meeting_transcript}")

    return {"role": "system", "content": [{"type": "text", "text": "\n\n".join(parts)}]}


def build_main_messages(
    session_id: str,
    speaker_id: str,
    user_profile: str,
    mem_context: str,
    active_tasks: str,
    pending_results: list[dict],
    vayumi_state: dict,
    meeting_transcript: str | None,
) -> list[dict]:
    messages = [
        {
            "role": "developer",
            "content": [{"type": "text", "text": build_main_developer_prompt(speaker_id, user_profile)}],
        },
        build_turn_context(mem_context, active_tasks, pending_results, vayumi_state, meeting_transcript),
    ]
    messages.extend(history_store.get(session_id))
    return messages


def build_sub_agent_prompt(
    task_id: str,
    task_description: str,
    tool_ids: list[str],
    skill_doc: str,
    max_steps: int,
) -> str:
    schemas = get_schemas_for_task(tool_ids) + [REPORT_SCHEMA]
    schema_block = json.dumps(schemas, indent=2)
    skill_section = f"\n\n[SKILL REFERENCE]\n{skill_doc}" if skill_doc else ""

    return (
        "You are a task executor. You do not talk to the user.\n"
        "Your only output is through report().\n"
        "Never write plain text. Always call a function.\n\n"
        f"TASK ID: {task_id}\n"
        f"TASK: {task_description}\n\n"
        "RULES:\n"
        "- report(STEP, ...) after each meaningful action\n"
        "- report(NEEDS_INFO, question) if blocked by user input\n"
        "- report(DONE, summary) when finished\n"
        "- report(ERROR, reason) if unrecoverable\n"
        "- report(CAPABILITY_GAP, what is missing) if tools are insufficient\n"
        f"- Maximum {max_steps} total function calls including report()\n\n"
        f"FUNCTIONS:\n{schema_block}{skill_section}"
    )
