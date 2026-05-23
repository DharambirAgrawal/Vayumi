from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class CapabilityBundle:
    """Declarative slice of tools + prompt for one sub-agent domain."""

    name: str
    prompt_path: Path
    allowed_tools: frozenset[str]
    tools_executed_as_main: frozenset[str] = frozenset()
    max_steps: int = 12
