from __future__ import annotations

from .constants import CAPABILITY_ROUTING

CAPABILITY_MENU = """[CAPABILITIES - delegate complex or multi-step tasks]
- research      : Web research, URL reading, multi-source synthesis
- communication : Email reading, searching, summarizing threads
- productivity  : Document generation (Word, PDF, Markdown), code execution
- data          : Data analysis, spreadsheet operations, calculations
"""


def resolve(capabilities: list[str]) -> list[str]:
    seen: list[str] = []
    for capability in capabilities:
        for tool_id in CAPABILITY_ROUTING.get(capability.strip(), []):
            if tool_id not in seen:
                seen.append(tool_id)
    return seen
