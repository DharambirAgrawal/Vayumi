# =============================================================================
# server/agents/task_agent.py — Task Agent (Multi-Step Execution)
# =============================================================================
#
# PURPOSE:
#   Handles complex, multi-step task execution. Activated when the orchestrator
#   detects a task that requires skill execution, multi-step reasoning, or
#   dependent operations. Uses smarter LLM models (llama-3.3-70b-versatile
#   via Groq, or Gemini for complex reasoning).
#
# WHEN ACTIVATED (from orchestrator intent classification):
#   - Task requires skill execution
#   - Task requires reading skill documentation first
#   - Task has more than 2 dependent steps
#   - Search needed + then reasoning on results
#   - MCP call + interpretation required
#   - Result quality check needed (self-review pass)
#
# MULTI-PASS EXECUTION EXAMPLE (from doc Section 7.2):
#   Turn: "Read the PDF I uploaded and list action items"
#     Pass 1: Orchestrator → intent: complex document task → route to TaskAgent
#     Pass 2: TaskAgent → read skill doc (SKILL.md) → plan steps
#     Pass 3: TaskAgent → execute plan → extract text → summarize
#     Pass 4: Orchestrator → format result → stream to user
#     Background: MemoryAgent logs the result
#
# CLASS: TaskAgent(BaseAgent)
#
#   __init__(self, llm_router, skill_runner, mcp_runner):
#
#   async run(self, context: AgentContext) -> AgentResult:
#     Main execution path. Steps:
#       1. Load relevant skill doc via skill_runner.load_skill_doc(skill_id)
#       2. Plan execution steps via LLM (smart model):
#          - Prompt includes: skill doc + user request + available MCPs
#          - LLM returns structured plan: list of steps
#       3. Execute plan step by step:
#          - For each step: call skill_runner.execute() or mcp_runner.execute()
#          - Collect intermediate results
#          - If a step fails → handle gracefully, report partial result
#       4. Assemble final result from all step outputs
#       5. Return AgentResult with response_text = final result
#
#   async _plan_steps(self, skill_doc: str, user_request: str,
#                     available_mcps: list) -> list[dict]:
#     Uses LLM to generate an execution plan.
#     Each step: {"action": "skill"|"mcp"|"llm", "target": str, "params": dict}
#
#   async _execute_step(self, step: dict, context: AgentContext) -> str:
#     Executes a single step of the plan.
#     Routes to skill_runner, mcp_runner, or LLM based on step["action"].
#
#   async _self_review(self, result: str, original_request: str) -> str:
#     Optional quality check pass. Asks LLM if the result adequately
#     answers the original request. If not, attempts refinement.
#
# DEFERRED TASKS (from doc Section 7.5):
#   When user says "Read this, I'll ask about it later":
#     1. Orchestrator detects: read intent + defer intent
#     2. Instant ack: "Got it, I'll read that and keep it ready."
#     3. TaskAgent runs skill in background → stores result in episodic memory
#        tagged: {user_id, artifact_type: "deferred_read", source_url, summary, created_at}
#     4. Later retrieval: Memory Agent finds it via semantic search + artifact_type filter
#
# IMPORTS NEEDED:
# =============================================================================

from __future__ import annotations

import json
import logging
import time
import traceback
from typing import Any

from server.agents.base_agent import BaseAgent, AgentContext, AgentResult
from server.llm.router import LLMRouter
from server.skills.skill_runner import SkillRunner
from server.mcps.mcp_runner import MCPRunner

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

_PLANNING_SYSTEM_PROMPT = """\
You are an execution planner inside an AI assistant. Given:
  • a SKILL document describing available skill capabilities,
  • a list of available MCP (Model-Context-Protocol) tools,
  • and the user's request,

produce a JSON array of execution steps. Each step is an object:

{
  "step": <1-based integer>,
  "action": "skill" | "mcp" | "llm",
  "target": "<skill_id or mcp_name or 'reason'>",
  "params": { ... },
  "description": "human-readable summary of what this step does"
}

Rules:
1. Use "skill" when a registered skill can fulfil the step.
2. Use "mcp" when an external MCP tool is the right choice.
3. Use "llm" when pure reasoning / summarisation / formatting is needed
   (target should be "reason"; params should contain a "prompt" key with
    the instruction, and may reference {{step_N}} to inject the output of
    step N).
4. Keep the plan minimal — do NOT add unnecessary steps.
5. Return ONLY the JSON array, no markdown fences, no commentary.\
"""

_PLANNING_USER_TEMPLATE = """\
=== SKILL DOCUMENTATION ===
{skill_doc}

=== AVAILABLE MCP TOOLS ===
{mcp_list}

=== USER REQUEST ===
{user_request}

=== PRIOR CONTEXT (recent messages) ===
{prior_context}

Produce the execution plan now.\
"""

_SELF_REVIEW_SYSTEM_PROMPT = """\
You are a quality-review module. You receive the ORIGINAL user request and
the RESULT produced by a multi-step execution pipeline.

Evaluate whether the result fully and correctly addresses the request.

Respond with EXACTLY one JSON object:
{
  "adequate": true | false,
  "issues": "description of gaps or errors (empty string if adequate)",
  "refined_result": "improved result text if not adequate, otherwise empty string"
}

Return ONLY the JSON object.\
"""

_SELF_REVIEW_USER_TEMPLATE = """\
=== ORIGINAL REQUEST ===
{original_request}

=== PRODUCED RESULT ===
{result}

Evaluate now.\
"""

_LLM_STEP_SYSTEM_PROMPT = """\
You are a reasoning sub-module inside an AI assistant's execution pipeline.
Follow the instruction precisely and return only the requested output.\
"""


class TaskAgent(BaseAgent):
    """Handles complex, multi-step task execution with planning and self-review."""

    # Maximum number of steps the planner is allowed to produce to guard
    # against runaway plans.
    MAX_PLAN_STEPS = 15

    def __init__(
        self,
        llm_router: LLMRouter,
        skill_runner: SkillRunner,
        mcp_runner: MCPRunner,
    ):
        self.llm_router = llm_router
        self.skill_runner = skill_runner
        self.mcp_runner = mcp_runner

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    async def run(self, context: AgentContext) -> AgentResult:
        """Execute a complex multi-step task.

        Pipeline:
            1. Resolve skill doc (if a skill_id is provided in context metadata).
            2. Ask the smart LLM to produce a step-by-step plan.
            3. Execute every step, collecting intermediate outputs.
            4. Assemble the final answer from step outputs.
            5. Optionally self-review for quality.
            6. Return the final ``AgentResult``.
        """
        start_ts = time.time()
        user_request: str = context.user_message
        metadata: dict[str, Any] = context.metadata or {}
        skill_id: str | None = metadata.get("skill_id")

        # ---- 1. Load skill documentation (best-effort) -----------------
        skill_doc = ""
        if skill_id:
            try:
                skill_doc = await self.skill_runner.load_skill_doc(skill_id)
            except Exception:
                logger.warning(
                    "Could not load skill doc for %s — proceeding without it",
                    skill_id,
                    exc_info=True,
                )

        # ---- 2. Discover available MCP tools ---------------------------
        available_mcps: list[str] = []
        try:
            raw_tools = await self.mcp_runner.list_tools()
            available_mcps = [
                tool.get("name", str(tool)) if isinstance(tool, dict) else str(tool)
                for tool in raw_tools
            ]
        except Exception:
            logger.warning(
                "Could not list MCP tools — proceeding without them",
                exc_info=True,
            )

        # ---- 3. Plan execution steps -----------------------------------
        try:
            plan = await self._plan_steps(
                skill_doc=skill_doc,
                user_request=user_request,
                available_mcps=available_mcps,
                context=context,
            )
        except Exception as exc:
            logger.error("Planning failed: %s", exc, exc_info=True)
            return AgentResult(
                response_text=(
                    "I understood the task but failed to build an execution plan. "
                    f"Error: {exc}"
                ),
                metadata={"error": str(exc), "agent": "task"},
            )

        if not plan:
            return AgentResult(
                response_text=(
                    "I analysed the request but could not determine any "
                    "actionable steps. Could you rephrase or provide more detail?"
                ),
                metadata={"agent": "task", "plan": []},
            )

        logger.info(
            "TaskAgent plan for request (%.40s…): %d step(s)",
            user_request,
            len(plan),
        )

        # ---- 4. Execute plan step-by-step ------------------------------
        step_outputs: dict[int, str] = {}
        errors: list[dict[str, Any]] = []

        for step in plan:
            step_num = step.get("step", 0)
            description = step.get("description", "")

            # Resolve {{step_N}} references inside params
            step = self._resolve_step_references(step, step_outputs)

            logger.info(
                "  → Executing step %d: %s [action=%s, target=%s]",
                step_num,
                description,
                step.get("action"),
                step.get("target"),
            )

            try:
                output = await self._execute_step(step, context)
                step_outputs[step_num] = output
                logger.debug("    Step %d output (%.200s…)", step_num, output)
            except Exception as exc:
                tb = traceback.format_exc()
                error_msg = f"Step {step_num} failed: {exc}"
                logger.error("    %s\n%s", error_msg, tb)
                step_outputs[step_num] = f"[ERROR] {error_msg}"
                errors.append({"step": step_num, "error": str(exc)})
                # Continue with remaining steps — partial results are
                # better than nothing.

        # ---- 5. Assemble final result ----------------------------------
        final_result = self._assemble_result(plan, step_outputs)

        # ---- 6. Self-review (optional quality gate) --------------------
        needs_review = metadata.get("self_review", len(plan) >= 3)
        if needs_review:
            try:
                final_result = await self._self_review(
                    result=final_result,
                    original_request=user_request,
                )
            except Exception:
                logger.warning(
                    "Self-review pass failed — using unreviewed result",
                    exc_info=True,
                )

        elapsed = time.time() - start_ts
        logger.info("TaskAgent completed in %.2fs", elapsed)

        return AgentResult(
            response_text=final_result,
            metadata={
                "agent": "task",
                "plan_steps": len(plan),
                "errors": errors,
                "elapsed_seconds": round(elapsed, 3),
            },
        )

    # ------------------------------------------------------------------
    # Planning
    # ------------------------------------------------------------------

    async def _plan_steps(
        self,
        skill_doc: str,
        user_request: str,
        available_mcps: list[str],
        context: AgentContext | None = None,
    ) -> list[dict]:
        """Use the smart LLM to generate a structured execution plan.

        Returns a list of step dicts, each with keys:
            step, action, target, params, description
        """
        # Build a concise representation of prior conversation for context.
        prior_context = ""
        if context and hasattr(context, "history") and context.history:
            recent = context.history[-6:]  # last few turns
            lines: list[str] = []
            for msg in recent:
                role = msg.get("role", "user")
                content = msg.get("content", "")
                lines.append(f"{role}: {content[:300]}")
            prior_context = "\n".join(lines)

        mcp_list_text = "\n".join(
            f"- {name}" for name in available_mcps
        ) if available_mcps else "(none available)"

        user_prompt = _PLANNING_USER_TEMPLATE.format(
            skill_doc=skill_doc or "(no skill doc loaded)",
            mcp_list=mcp_list_text,
            user_request=user_request,
            prior_context=prior_context or "(none)",
        )

        raw = await self.llm_router.generate(
            messages=[
                {"role": "system", "content": _PLANNING_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            model_tier="smart",  # route to 70b / Gemini
        )

        plan = self._parse_plan_json(raw)
        return plan

    def _parse_plan_json(self, raw: str) -> list[dict]:
        """Robustly parse the LLM's plan output into a list of step dicts."""
        text = raw.strip()

        # Strip markdown code fences if the model added them despite instructions.
        if text.startswith("```"):
            # Remove opening fence (```json or ```)
            first_newline = text.index("\n") if "\n" in text else 3
            text = text[first_newline + 1:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()

        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            # Attempt to find the first '[' and last ']' as a fallback.
            start = text.find("[")
            end = text.rfind("]")
            if start != -1 and end != -1 and end > start:
                try:
                    parsed = json.loads(text[start : end + 1])
                except json.JSONDecodeError as exc:
                    raise ValueError(
                        f"LLM returned unparseable plan. Raw output:\n{raw[:500]}"
                    ) from exc
            else:
                raise ValueError(
                    f"LLM plan output does not contain a JSON array. "
                    f"Raw output:\n{raw[:500]}"
                )

        if not isinstance(parsed, list):
            raise ValueError(
                f"Expected a JSON array from the planner, got {type(parsed).__name__}"
            )

        # Validate and normalise each step.
        validated: list[dict] = []
        for idx, item in enumerate(parsed[: self.MAX_PLAN_STEPS]):
            if not isinstance(item, dict):
                logger.warning("Skipping non-dict plan element at index %d", idx)
                continue
            step: dict[str, Any] = {
                "step": item.get("step", idx + 1),
                "action": item.get("action", "llm"),
                "target": item.get("target", "reason"),
                "params": item.get("params") or {},
                "description": item.get("description", ""),
            }
            if step["action"] not in ("skill", "mcp", "llm"):
                logger.warning(
                    "Unknown action '%s' in plan step %d — defaulting to 'llm'",
                    step["action"],
                    step["step"],
                )
                step["action"] = "llm"
            validated.append(step)

        return validated

    # ------------------------------------------------------------------
    # Step execution
    # ------------------------------------------------------------------

    async def _execute_step(self, step: dict, context: AgentContext) -> str:
        """Execute a single plan step and return its textual output."""
        action: str = step["action"]
        target: str = step["target"]
        params: dict[str, Any] = step.get("params", {})

        if action == "skill":
            return await self._execute_skill_step(target, params, context)
        elif action == "mcp":
            return await self._execute_mcp_step(target, params, context)
        elif action == "llm":
            return await self._execute_llm_step(params, context)
        else:
            raise ValueError(f"Unknown step action: {action}")

    async def _execute_skill_step(
        self, skill_id: str, params: dict[str, Any], context: AgentContext
    ) -> str:
        """Run a skill via SkillRunner and return the output as a string."""
        result = await self.skill_runner.execute(
            skill_id=skill_id,
            params=params,
            context={
                "user_id": getattr(context, "user_id", None),
                "session_id": getattr(context, "session_id", None),
                "user_message": context.user_message,
            },
        )
        # Normalise to string — skills may return dicts, lists, etc.
        if isinstance(result, str):
            return result
        return json.dumps(result, ensure_ascii=False, default=str)

    async def _execute_mcp_step(
        self, mcp_name: str, params: dict[str, Any], context: AgentContext
    ) -> str:
        """Call an MCP tool via MCPRunner and return the output as a string."""
        result = await self.mcp_runner.execute(
            tool_name=mcp_name,
            params=params,
            context={
                "user_id": getattr(context, "user_id", None),
                "session_id": getattr(context, "session_id", None),
            },
        )
        if isinstance(result, str):
            return result
        return json.dumps(result, ensure_ascii=False, default=str)

    async def _execute_llm_step(
        self, params: dict[str, Any], context: AgentContext
    ) -> str:
        """Pure LLM reasoning / summarisation / formatting step."""
        prompt = params.get("prompt", "")
        if not prompt:
            raise ValueError("LLM step requires a 'prompt' in params")

        # Allow the plan to specify a model tier; default to smart.
        model_tier = params.get("model_tier", "smart")

        messages = [
            {"role": "system", "content": _LLM_STEP_SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ]

        result = await self.llm_router.generate(
            messages=messages,
            model_tier=model_tier,
        )
        return result.strip()

    # ------------------------------------------------------------------
    # Inter-step reference resolution
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_step_references(
        step: dict, step_outputs: dict[int, str]
    ) -> dict:
        """Replace ``{{step_N}}`` placeholders in params with actual outputs."""
        params = step.get("params", {})
        if not params:
            return step

        resolved_params: dict[str, Any] = {}
        for key, value in params.items():
            if isinstance(value, str):
                for step_num, output in step_outputs.items():
                    placeholder = "{{step_" + str(step_num) + "}}"
                    value = value.replace(placeholder, output)
            resolved_params[key] = value

        return {**step, "params": resolved_params}

    # ------------------------------------------------------------------
    # Result assembly
    # ------------------------------------------------------------------

    @staticmethod
    def _assemble_result(
        plan: list[dict], step_outputs: dict[int, str]
    ) -> str:
        """Combine step outputs into the final answer.

        Strategy: if the last step is an LLM reasoning step (i.e. a
        summarisation / formatting step), its output is the final answer.
        Otherwise, concatenate the meaningful outputs.
        """
        if not step_outputs:
            return "No results were produced during execution."

        last_step = plan[-1] if plan else None
        if last_step and last_step.get("action") == "llm":
            last_num = last_step.get("step", max(step_outputs.keys()))
            if last_num in step_outputs:
                output = step_outputs[last_num]
                if not output.startswith("[ERROR]"):
                    return output

        # Fallback: concatenate all non-error outputs.
        parts: list[str] = []
        for step in plan:
            num = step.get("step", 0)
            output = step_outputs.get(num, "")
            if output and not output.startswith("[ERROR]"):
                parts.append(output)

        if parts:
            return "\n\n".join(parts)

        # Everything errored — return a summary of errors.
        error_lines = [
            step_outputs[s.get("step", 0)]
            for s in plan
            if step_outputs.get(s.get("step", 0), "").startswith("[ERROR]")
        ]
        return (
            "The task could not be completed. Errors encountered:\n"
            + "\n".join(error_lines)
        )

    # ------------------------------------------------------------------
    # Self-review
    # ------------------------------------------------------------------

    async def _self_review(self, result: str, original_request: str) -> str:
        """Quality-check the assembled result via an LLM pass.

        If the LLM deems the result inadequate it returns a refined version.
        Otherwise the original result is returned unchanged.
        """
        user_prompt = _SELF_REVIEW_USER_TEMPLATE.format(
            original_request=original_request,
            result=result,
        )

        raw = await self.llm_router.generate(
            messages=[
                {"role": "system", "content": _SELF_REVIEW_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            model_tier="smart",
        )

        review = self._parse_review_json(raw)

        if review.get("adequate", True):
            logger.info("Self-review: result deemed adequate.")
            return result

        refined = review.get("refined_result", "").strip()
        if refined:
            logger.info(
                "Self-review: result refined. Issues: %s",
                review.get("issues", ""),
            )
            return refined

        # Review said not adequate but didn't produce a refinement — keep
        # the original to avoid losing content.
        logger.warning(
            "Self-review flagged issues but produced no refinement: %s",
            review.get("issues", ""),
        )
        return result

    @staticmethod
    def _parse_review_json(raw: str) -> dict:
        """Parse the self-review LLM output into a dict."""
        text = raw.strip()
        if text.startswith("```"):
            first_newline = text.index("\n") if "\n" in text else 3
            text = text[first_newline + 1:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()

        try:
            parsed = json.loads(text)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            # Try to extract JSON object between { and }
            start = text.find("{")
            end = text.rfind("}")
            if start != -1 and end != -1 and end > start:
                try:
                    parsed = json.loads(text[start : end + 1])
                    if isinstance(parsed, dict):
                        return parsed
                except json.JSONDecodeError:
                    pass

        logger.warning("Could not parse self-review output — treating as adequate")
        return {"adequate": True, "issues": "", "refined_result": ""}