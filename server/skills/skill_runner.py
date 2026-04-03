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
import sys
import asyncio
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

SKILL_TIMEOUT_SECONDS = 30


class SkillRunner:
    """
    Loads skill metadata from a lightweight registry, resolves skill docs
    on demand, and executes skill scripts in isolated subprocesses.
    """

    def __init__(self, registry_path: str = "server/skills/skill_registry.json"):
        self.registry_path = Path(registry_path)
        self.registry: dict = self._load_registry()

    # --------------------------------------------------------------------- #
    #  Registry loading & validation                                         #
    # --------------------------------------------------------------------- #

    def _load_registry(self) -> dict:
        """
        Parse skill_registry.json and do basic structural validation.
        Returns the parsed dict.  If the file is missing or malformed we
        log a warning and fall back to an empty registry so the rest of
        the system keeps running.
        """
        if not self.registry_path.exists():
            logger.warning(
                "Skill registry not found at %s — no skills available.",
                self.registry_path,
            )
            return {"skills": []}

        try:
            raw = self.registry_path.read_text(encoding="utf-8")
            data = json.loads(raw)
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning(
                "Failed to read skill registry at %s: %s — no skills available.",
                self.registry_path,
                exc,
            )
            return {"skills": []}

        # --- validate top-level shape ---
        if not isinstance(data, dict) or "skills" not in data:
            logger.warning(
                "Skill registry missing 'skills' key — no skills available."
            )
            return {"skills": []}

        if not isinstance(data["skills"], list):
            logger.warning(
                "Skill registry 'skills' is not a list — no skills available."
            )
            return {"skills": []}

        # --- validate each entry ---
        required_keys = {"id", "name", "description", "trigger_keywords", "doc_path"}
        valid_skills: list[dict] = []

        for entry in data["skills"]:
            if not isinstance(entry, dict):
                logger.warning("Skipping non-dict skill entry: %s", entry)
                continue

            missing = required_keys - entry.keys()
            if missing:
                logger.warning(
                    "Skill entry '%s' missing keys %s — skipping.",
                    entry.get("id", "<unknown>"),
                    missing,
                )
                continue

            valid_skills.append(entry)

        data["skills"] = valid_skills
        logger.info(
            "Loaded skill registry with %d skill(s): %s",
            len(valid_skills),
            [s["id"] for s in valid_skills],
        )
        return data

    # --------------------------------------------------------------------- #
    #  Public helpers                                                         #
    # --------------------------------------------------------------------- #

    def get_registry_summary(self) -> list[dict]:
        """
        Return a slim list of ``{id, name, description}`` dicts — just enough
        for the LLM to know which skills exist.  This is the ~100-token
        payload that lives in the system prompt at all times.
        """
        return [
            {
                "id": skill["id"],
                "name": skill["name"],
                "description": skill["description"],
            }
            for skill in self.registry.get("skills", [])
        ]

    def find_skill(self, text: str) -> dict | None:
        """
        Scan the registry for a skill whose ``trigger_keywords`` appear in
        *text* (case-insensitive).  Returns the first matching skill entry
        dict, or ``None`` if nothing matches.
        """
        if not text:
            return None

        text_lower = text.lower()

        for skill in self.registry.get("skills", []):
            keywords = skill.get("trigger_keywords", [])
            for keyword in keywords:
                if keyword.lower() in text_lower:
                    logger.info(
                        "Matched skill '%s' via keyword '%s'.",
                        skill["id"],
                        keyword,
                    )
                    return skill

        return None

    # --------------------------------------------------------------------- #
    #  Skill-doc loading                                                      #
    # --------------------------------------------------------------------- #

    async def load_skill_doc(self, skill_id: str) -> str:
        """
        Read and return the full ``SKILL.md`` content for *skill_id*.

        The path is resolved from the registry's ``doc_path`` field.  If the
        skill id is unknown or the file doesn't exist, an informative error
        string is returned instead so the caller never gets an exception.
        """
        skill_entry = self._find_entry_by_id(skill_id)
        if skill_entry is None:
            msg = f"Unknown skill id: {skill_id}"
            logger.warning(msg)
            return msg

        doc_path = Path(skill_entry["doc_path"])
        if not doc_path.exists():
            msg = f"SKILL.md not found for '{skill_id}' at {doc_path}"
            logger.warning(msg)
            return msg

        # read_text is fast (local file), but run in executor to stay
        # non-blocking on the off chance the filesystem is slow / NFS.
        loop = asyncio.get_running_loop()
        content = await loop.run_in_executor(
            None, doc_path.read_text, "utf-8"
        )
        logger.info(
            "Loaded SKILL.md for '%s' (%d chars).", skill_id, len(content)
        )
        return content

    # --------------------------------------------------------------------- #
    #  Skill execution                                                        #
    # --------------------------------------------------------------------- #

    async def execute(
        self,
        skill_id: str,
        input_data: dict | None = None,
        params: dict | None = None,
        context: dict | None = None,
        session=None,
        **kwargs,
    ) -> dict:
        """
        Execute a skill's ``run.py`` in a subprocess.

        1. Write *input_data* → ``skills/<skill_id>/input.json``
        2. Spawn ``python run.py`` inside that directory (30 s timeout)
        3. Read ``skills/<skill_id>/output.json``
        4. Return the parsed dict

        Every failure path returns a dict with
        ``{"success": False, "error": "<reason>"}`` — the caller never
        sees a raised exception from this method.
        """
        skill_entry = self._find_entry_by_id(skill_id)
        if skill_entry is None:
            return {"success": False, "error": f"Unknown skill id: {skill_id}"}

        # Backwards-compatible normalization: callers may pass params/context
        # instead of a raw input_data payload.
        payload = input_data
        if payload is None:
            payload = params if params is not None else {}
        if context:
            payload = {**context, **payload}
        if kwargs:
            payload = {**payload, **kwargs}

        # Resolve the skill directory from the doc_path (parent of SKILL.md)
        skill_dir = Path(skill_entry["doc_path"]).parent
        run_script = skill_dir / "run.py"
        input_file = skill_dir / "input.json"
        output_file = skill_dir / "output.json"

        if not run_script.exists():
            return {
                "success": False,
                "error": f"run.py not found for skill '{skill_id}' at {run_script}",
            }

        # ---- 1. Write input.json ---------------------------------------- #
        try:
            input_file.write_text(
                json.dumps(payload, indent=2, default=str),
                encoding="utf-8",
            )
        except OSError as exc:
            return {
                "success": False,
                "error": f"Failed to write input.json: {exc}",
            }

        # ---- 2. Remove stale output.json (if any) ----------------------- #
        if output_file.exists():
            try:
                output_file.unlink()
            except OSError:
                pass  # best-effort cleanup

        # ---- 3. Run the subprocess --------------------------------------- #
        try:
            process = await asyncio.create_subprocess_exec(
                sys.executable,
                str(run_script.name),
                cwd=str(skill_dir),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=SKILL_TIMEOUT_SECONDS,
            )

        except asyncio.TimeoutError:
            # Kill the runaway process before returning
            try:
                process.kill()  # type: ignore[possibly-undefined]
                await process.wait()  # type: ignore[possibly-undefined]
            except Exception:
                pass
            logger.error("Skill '%s' timed out after %ds.", skill_id, SKILL_TIMEOUT_SECONDS)
            return {"success": False, "error": "Skill timed out"}

        except Exception as exc:
            logger.error("Skill '%s' subprocess launch failed: %s", skill_id, exc)
            return {"success": False, "error": "Skill execution failed"}

        # ---- 4. Check return code ---------------------------------------- #
        if process.returncode != 0:
            stderr_text = stderr.decode(errors="replace").strip() if stderr else ""
            logger.error(
                "Skill '%s' exited with code %d. stderr: %s",
                skill_id,
                process.returncode,
                stderr_text[:500],
            )
            return {
                "success": False,
                "error": "Skill execution failed",
                "details": stderr_text[:500] if stderr_text else None,
            }

        # ---- 5. Read output.json ----------------------------------------- #
        if not output_file.exists():
            logger.error("Skill '%s' did not produce output.json.", skill_id)
            return {"success": False, "error": "No output produced"}

        try:
            raw_output = output_file.read_text(encoding="utf-8")
            result = json.loads(raw_output)
        except (json.JSONDecodeError, OSError) as exc:
            logger.error(
                "Skill '%s' output.json unreadable: %s", skill_id, exc
            )
            return {
                "success": False,
                "error": f"Failed to read output.json: {exc}",
            }

        logger.info("Skill '%s' executed successfully.", skill_id)
        return result

    async def run(self, *args, **kwargs) -> dict:
        """Compatibility alias for callers that expect a ``run`` method."""
        return await self.execute(*args, **kwargs)

    # --------------------------------------------------------------------- #
    #  Internal helpers                                                       #
    # --------------------------------------------------------------------- #

    def _find_entry_by_id(self, skill_id: str) -> dict | None:
        """Look up a skill entry in the registry by its ``id`` field."""
        for skill in self.registry.get("skills", []):
            if skill["id"] == skill_id:
                return skill
        return None