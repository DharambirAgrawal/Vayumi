# =============================================================================
# server/skills/skill_runner.py — Skill Loader & Executor
# =============================================================================
#
# PURPOSE:
#   Loads skill documentation (SKILL.md) and executes skill logic (run.py)
#   on demand. Skills are independent add-ons — adding/removing a skill
#   requires zero changes to this file or the core system.
#
# SKILL STRUCTURE (each skill is a directory):
#   skills/<skill_id>/
#     ├── SKILL.md     — Documentation: description, input format, output format,
#     │                   requirements, examples. Read by TaskAgent to understand
#     │                   how to use the skill.
#     └── run.py       — Execution script. Reads input.json, writes output.json.
#                         Must complete within 30 seconds.
#                         Must handle errors gracefully (write error to output.json).
#
# SKILL REGISTRY (skill_registry.json):
#   Lightweight index — ONLY names and one-line descriptions (~100 tokens total).
#   Full skill doc is NEVER loaded unless that skill is being executed.
#   Format:
#     {
#       "skills": [
#         {
#           "id": "web_reader",
#           "name": "Web Reader",
#           "description": "Given a URL, reads the page content and answers questions about it",
#           "trigger_keywords": ["url", "website", "read this link", "open this"],
#           "doc_path": "skills/web_reader/SKILL.md"
#         }
#       ]
#     }
#
# CLASS: SkillRunner
#
#   __init__(self, registry_path: str = "server/skills/skill_registry.json"):
#     - Loads skill_registry.json into self.registry
#     - Parses and validates the registry structure
#
#   def get_registry_summary(self) -> list[dict]:
#     Returns list of {id, name, description} for context injection.
#     This is what stays in the LLM context at all times (~100 tokens).
#
#   def find_skill(self, text: str) -> dict | None:
#     Searches registry for a matching skill based on trigger_keywords.
#     Returns the skill entry dict or None if no match.
#
#   async def load_skill_doc(self, skill_id: str) -> str:
#     Reads and returns the full SKILL.md content for the given skill_id.
#     This is injected into LLM context only when that skill is being executed.
#     Returns the markdown content as a string.
#
#   async def execute(self, skill_id: str, input_data: dict) -> dict:
#     Executes a skill's run.py.
#     Steps:
#       1. Write input_data to skills/<skill_id>/input.json
#       2. Run skills/<skill_id>/run.py as a subprocess with 30s timeout
#       3. Read skills/<skill_id>/output.json
#       4. Return parsed output dict
#     Error handling:
#       - Timeout (>30s) → return {"success": False, "error": "Skill timed out"}
#       - Crash → return {"success": False, "error": "Skill execution failed"}
#       - Missing output.json → return {"success": False, "error": "No output produced"}
#
# SKILL INTERFACE CONTRACT (every skill must follow):
#   1. Have a SKILL.md with: description, input format, output format, requirements, example
#   2. Have a run.py that reads input.json and writes output.json
#   3. Complete within 30 seconds
#   4. Handle errors gracefully (write error to output.json, never crash silently)
#
# IMPORTS NEEDED:
# =============================================================================

import json
import asyncio
from pathlib import Path


class SkillRunner:
    def __init__(self, registry_path: str = "server/skills/skill_registry.json"):
        self.registry_path = Path(registry_path)
        self.registry: dict = {}

    def get_registry_summary(self) -> list[dict]:
        pass

    def find_skill(self, text: str) -> dict | None:
        pass

    async def load_skill_doc(self, skill_id: str) -> str:
        pass

    async def execute(self, skill_id: str, input_data: dict) -> dict:
        pass
