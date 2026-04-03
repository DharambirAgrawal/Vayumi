# =============================================================================
# server/core/orchestrator.py — Central Consciousness (The Brain)
# =============================================================================

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

from server.llm.router import LLMRouter
from server.core.context_builder import ContextBuilder
from server.agents.task_agent import TaskAgent
from server.agents.search_agent import SearchAgent
from server.agents.memory_agent import MemoryAgent
from server.skills.skill_runner import SkillRunner
from server.mcps.mcp_runner import MCPRunner

logger = logging.getLogger(__name__)


# =============================================================================
# PERMANENT SYSTEM PROMPT (~300 tokens, never changes)
# =============================================================================

SYSTEM_PROMPT = """You are Vayumi, a superhuman personal AI agent.
You are always aware of:
- Who you are serving (the authenticated user's profile)
- Who is speaking (speaker_id from diarizer)
- What mode you are in (normal / meeting / focus)
- What context is active (loaded from context engine)
- What skills and tools are available (from registry summaries)

Your job in each turn:
1. Understand intent
2. Decide: respond directly OR route to skill/tool OR run multi-step
3. Never fake capabilities — if you cannot do it, say so honestly
4. Respond naturally like a human assistant would
5. Be brief unless depth is needed"""


# =============================================================================
# INTENT CLASSIFICATION PROMPT
# =============================================================================

INTENT_CLASSIFICATION_PROMPT = """Analyze the user's message and determine the appropriate action.

Available skills: {skills_summary}
Available MCPs (tools): {mcps_summary}

User message: "{text}"

Respond with a JSON object:
{{
  "intent_type": "conversation" | "skill" | "mcp" | "complex" | "search" | "no_action",
  "skill_id": "skill_name or null",
  "mcp_name": "mcp_name or null", 
  "needs_task_agent": true/false,
  "needs_search": true/false,
  "response_text": "direct response if conversation, else null",
  "reasoning": "brief explanation of your decision"
}}

Rules:
- "conversation": Simple chat, greetings, questions you can answer directly
- "skill": User wants a specific capability (check available skills)
- "mcp": User wants to use an external tool (check available MCPs)
- "complex": Multi-step task requiring planning and execution
- "search": User needs information you should search for
- "no_action": Not addressed to you, or background conversation

If intent_type is "conversation", provide the response_text directly.
Only set needs_task_agent=true for multi-step tasks.
Only set needs_search=true if external information is needed."""


# =============================================================================
# ACKNOWLEDGMENT TEMPLATES (for sub-500ms response)
# =============================================================================

ACK_TEMPLATES = {
    "skill": "Sure, let me {action} for you.",
    "mcp": "On it, accessing {tool} now.",
    "search": "Let me look that up for you.",
    "complex": "Working on that now, give me a moment.",
    "default": "Got it, working on that."
}

ACK_ACTIONS = {
    "email": "check your email",
    "calendar": "check your calendar",
    "read": "read that",
    "write": "write that",
    "search": "search for that",
    "calculate": "calculate that",
    "summarize": "summarize that",
    "translate": "translate that",
}


# =============================================================================
# MULTI-RUN TRIGGERS
# =============================================================================

MULTI_RUN_TRIGGERS = [
    "task requires skill execution",
    "task requires reading skill documentation first",
    "task has more than 2 dependent steps",
    "search needed + then reasoning on results",
    "MCP call + interpretation required",
    "result quality check needed (self-review pass)"
]


# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass
class IntentResult:
    """Result of intent classification."""
    intent_type: str  # "conversation" | "skill" | "mcp" | "complex" | "search" | "no_action"
    skill_id: str | None = None
    mcp_name: str | None = None
    mcp_params: dict = field(default_factory=dict)
    needs_task_agent: bool = False
    needs_search: bool = False
    response_text: str | None = None
    reasoning: str | None = None


@dataclass
class OrchestrationResult:
    """Result of orchestration run."""
    response: str | None = None
    ack: str | None = None
    result: str | None = None
    error: str | None = None
    duration_ms: float = 0
    intent: IntentResult | None = None


# =============================================================================
# ORCHESTRATOR CLASS
# =============================================================================

class Orchestrator:
    """
    The Central Consciousness — coordinates all AI subsystems.
    
    Receives parsed input, builds context, decides what agents to run,
    coordinates them, assembles the final response, and streams it back.
    """
    
    # Timeout for instant acknowledgment generation
    ACK_TIMEOUT_MS = 500
    
    # Timeout for intent classification
    INTENT_TIMEOUT_MS = 2000

    def __init__(
        self,
        llm_router: LLMRouter,
        context_builder: ContextBuilder,
        task_agent: TaskAgent,
        search_agent: SearchAgent,
        memory_agent: MemoryAgent,
        skill_runner: SkillRunner,
        mcp_runner: MCPRunner
    ):
        self.llm_router = llm_router
        self.context_builder = context_builder
        self.task_agent = task_agent
        self.search_agent = search_agent
        self.memory_agent = memory_agent
        self.skill_runner = skill_runner
        self.mcp_runner = mcp_runner

    async def run(self, session, context: dict, text: str) -> str | dict | None:
        """
        Main orchestration entry point.
        
        Args:
            session: Current user session with user_id, mode, etc.
            context: Built context from context_builder
            text: User's input text
            
        Returns:
            - str: Direct response text
            - dict: {"ack": str, "result": str} for long tasks
            - None: No action needed (handler ignores)
        """
        start_time = time.time()
        
        try:
            # Step 1: Classify intent
            intent = await self._classify_intent(session, context, text)
            
            # Step 2: Handle based on intent type
            if intent.intent_type == "no_action":
                return None
            
            if intent.intent_type == "conversation":
                response = await self._generate_conversational_response(
                    session, context, text, intent,
                )
                asyncio.create_task(
                    self._background_memory_update(session, text, response)
                )
                return response
            
            # Step 3: For non-trivial intents, check if we need long task handling
            if self._needs_long_task_handling(intent):
                return await self._handle_long_task(session, context, text, intent)
            
            # Step 4: Handle simple skill/MCP calls
            if intent.intent_type == "skill":
                result = await self._execute_skill(session, context, intent)
                formatted = await self.format_result(session, result)
                asyncio.create_task(
                    self._background_memory_update(session, text, formatted)
                )
                return formatted
            
            if intent.intent_type == "mcp":
                result = await self._execute_mcp(session, context, intent)
                formatted = await self.format_result(session, result)
                asyncio.create_task(
                    self._background_memory_update(session, text, formatted)
                )
                return formatted
            
            if intent.intent_type == "search":
                result = await self._execute_search(session, context, text, intent)
                formatted = await self.format_result(session, result)
                asyncio.create_task(
                    self._background_memory_update(session, text, formatted)
                )
                return formatted
            
            # Step 5: Complex multi-agent task
            if intent.intent_type == "complex":
                return await self._handle_complex_task(session, context, text, intent)
            
            # Fallback
            return "I'm not sure how to help with that. Could you rephrase?"
            
        except asyncio.TimeoutError:
            return "I'm taking longer than expected. Let me try again."
        except Exception as e:
            # Log error but return graceful message
            return f"I encountered an issue: {str(e)[:100]}. Please try again."

    async def _classify_intent(
        self,
        session,
        context: dict,
        text: str
    ) -> IntentResult:
        """
        Classify user's intent using fast LLM call.
        
        Uses llama-3.1-8b-instant via Groq for speed.
        """
        # Build classification prompt
        skills_summary = context.get("skill_summary") or context.get("skills_summary") or "No skills available"
        mcps_summary = context.get("mcp_summary") or context.get("mcps_summary") or "No MCPs available"
        reading_context = context.get("reading_context") or ""
        
        classification_prompt = INTENT_CLASSIFICATION_PROMPT.format(
            skills_summary=skills_summary,
            mcps_summary=mcps_summary,
            text=text
        )
        
        messages: list[dict[str, str]] = [
            {"role": "system", "content": SYSTEM_PROMPT},
        ]

        # Inject reading/article context first so the classifier knows what "that article" refers to
        if reading_context:
            messages.append({
                "role": "user",
                "content": f"Recent article context:\n{reading_context}",
            })

        # Inject recent conversation so the classifier can resolve pronouns / follow-ups
        recent_turns = context.get("conversation_window") or context.get("recent_turns") or []
        if recent_turns:
            last_turns = recent_turns[-6:]
            lines = []
            for turn in last_turns:
                if isinstance(turn, dict):
                    lines.append(f"{turn.get('role','user')}: {turn.get('content','')}")
                else:
                    lines.append(str(turn))
            history_text = "\n".join(lines)
            messages.append({
                "role": "user",
                "content": f"Recent conversation:\n{history_text}",
            })

        # Classification prompt comes last so the model sees full context first
        messages.append({"role": "user", "content": classification_prompt})
        
        try:
            response = await asyncio.wait_for(
                self.llm_router.call(
                    user_id=session.user_id,
                    task_type="orchestrate",
                    messages=messages,
                    max_tokens=300
                ),
                timeout=self.INTENT_TIMEOUT_MS / 1000
            )
            
            return self._parse_intent_response(response)
            
        except asyncio.TimeoutError:
            # Default to conversation on timeout
            return IntentResult(
                intent_type="conversation",
                response_text="I'm here to help. Could you tell me more about what you need?"
            )
        except Exception:
            # Default to conversation on error
            return IntentResult(
                intent_type="conversation", 
                response_text="I didn't quite catch that. Could you rephrase?"
            )

    async def _generate_conversational_response(
        self,
        session,
        context: dict,
        text: str,
        intent: IntentResult,
    ) -> str:
        """Generate a full conversational response using the LLM with proper context.

        The intent classifier's inline ``response_text`` works for trivial greetings,
        but fails for follow-up questions that depend on conversation history or
        article context (e.g. "who is the author of that article"). This method
        makes a dedicated LLM call with the full context window so the model can
        resolve references and give accurate answers.
        """
        # For very short / trivial replies the classifier already nailed, skip the extra call
        classifier_reply = intent.response_text or ""
        if classifier_reply and self._is_trivial_reply(classifier_reply, text):
            return classifier_reply

        # Build message list with full context
        messages: list[dict[str, str]] = [{"role": "system", "content": SYSTEM_PROMPT}]

        # Inject user identity
        user_identity = context.get("user_identity", "")
        if user_identity:
            messages[0]["content"] += f"\n\n{user_identity}"

        # Inject reading/article context so follow-ups about a URL work
        reading_context = context.get("reading_context", "")
        if reading_context:
            messages.append({"role": "system", "content": reading_context})

        # Inject retrieved memories
        memories = context.get("memories", "")
        if memories:
            messages.append({"role": "system", "content": f"[Relevant Memories]\n{memories}"})

        # Replay conversation history so the model sees prior turns
        recent_turns = context.get("conversation_window") or []
        for turn in recent_turns:
            if isinstance(turn, dict):
                role = turn.get("role", "user")
                content = turn.get("content") or turn.get("text", "")
            elif isinstance(turn, str) and ": " in turn:
                role, content = turn.split(": ", 1)
                role = "assistant" if role.strip().lower() == "assistant" else "user"
            else:
                role, content = "user", str(turn)
            if content:
                messages.append({"role": role, "content": content})

        # Current user input
        messages.append({"role": "user", "content": text})

        try:
            response = await self.llm_router.call(
                user_id=session.user_id,
                task_type="orchestrate",
                messages=messages,
                max_tokens=500,
            )
            return response.strip() if response else classifier_reply or "I'm here to help."
        except Exception:
            logger.warning("Conversational LLM call failed, falling back to classifier reply", exc_info=True)
            return classifier_reply or "I didn't quite catch that. Could you rephrase?"

    @staticmethod
    def _is_trivial_reply(reply: str, user_text: str) -> bool:
        """Return True for replies to greetings / small talk where the classifier is good enough."""
        trivial_intents = {"hi", "hello", "hey", "how are you", "thanks", "thank you", "bye", "goodbye", "ok", "okay"}
        return user_text.strip().lower().rstrip("!?.") in trivial_intents

    def _parse_intent_response(self, response: str) -> IntentResult:
        """Parse LLM response into IntentResult."""
        try:
            # Try to extract JSON from response
            # Handle cases where LLM wraps in markdown code blocks
            cleaned = response.strip()
            if cleaned.startswith("```"):
                lines = cleaned.split("\n")
                json_lines = []
                in_json = False
                for line in lines:
                    if line.startswith("```") and not in_json:
                        in_json = True
                        continue
                    elif line.startswith("```") and in_json:
                        break
                    elif in_json:
                        json_lines.append(line)
                cleaned = "\n".join(json_lines)
            
            # Find JSON object in response
            start = cleaned.find("{")
            end = cleaned.rfind("}") + 1
            if start != -1 and end > start:
                json_str = cleaned[start:end]
                data = json.loads(json_str)
                
                return IntentResult(
                    intent_type=data.get("intent_type", "conversation"),
                    skill_id=data.get("skill_id"),
                    mcp_name=data.get("mcp_name"),
                    mcp_params=data.get("mcp_params", {}),
                    needs_task_agent=data.get("needs_task_agent", False),
                    needs_search=data.get("needs_search", False),
                    response_text=data.get("response_text"),
                    reasoning=data.get("reasoning")
                )
                
        except (json.JSONDecodeError, KeyError, TypeError):
            pass
        
        # Fallback: treat as conversation with the raw response
        return IntentResult(
            intent_type="conversation",
            response_text=response if len(response) < 500 else response[:500]
        )

    def _needs_long_task_handling(self, intent: IntentResult) -> bool:
        """Determine if task needs ack + background processing pattern."""
        if intent.needs_task_agent:
            return True
        if intent.needs_search and intent.intent_type == "complex":
            return True
        if intent.intent_type == "complex":
            return True
        return False

    async def _handle_long_task(
        self,
        session,
        context: dict,
        text: str,
        intent: IntentResult
    ) -> dict:
        """
        Handle long-running tasks with instant ack + background processing.
        
        Returns dict with 'ack' and 'result' keys.
        """
        # Generate instant acknowledgment (must be fast)
        ack_task = asyncio.create_task(self._generate_instant_ack(intent))
        
        # Start the actual work
        work_task = asyncio.create_task(
            self._execute_long_task(session, context, text, intent)
        )
        
        # Wait for ack with timeout
        try:
            ack = await asyncio.wait_for(ack_task, timeout=self.ACK_TIMEOUT_MS / 1000)
        except asyncio.TimeoutError:
            ack = ACK_TEMPLATES["default"]
        
        # Wait for work to complete
        try:
            result = await work_task
            formatted_result = await self.format_result(session, result)
        except Exception as e:
            formatted_result = f"I ran into an issue: {str(e)[:100]}"
        
        # Background memory update
        asyncio.create_task(
            self._background_memory_update(session, text, formatted_result)
        )
        
        return {"ack": ack, "result": formatted_result}

    async def _execute_long_task(
        self,
        session,
        context: dict,
        text: str,
        intent: IntentResult
    ) -> str:
        """Execute the actual long-running task."""
        results = []
        
        # Run search if needed
        if intent.needs_search:
            search_context = SimpleNamespace(
                user_message=text,
                metadata={},
                user_id=getattr(session, "user_id", None),
                session_id=getattr(session, "session_id", None),
                history=context.get("conversation_window", []),
            )
            search_result = await self.search_agent.run(search_context)
            results.append(f"Search findings:\n{getattr(search_result, 'response_text', str(search_result))}")
        
        # Run task agent if needed
        if intent.needs_task_agent or intent.intent_type == "complex":
            task_result = await self.task_agent.run(
                session=session,
                task=text,
                context=context,
                search_results=results[0] if results else None
            )
            results.append(task_result)
        
        # Execute skill if specified
        if intent.skill_id:
            skill_result = await self._execute_skill(session, context, intent)
            results.append(skill_result)
        
        # Execute MCP if specified
        if intent.mcp_name:
            mcp_result = await self._execute_mcp(session, context, intent)
            results.append(mcp_result)
        
        return "\n\n".join(results) if results else "Task completed."

    async def _generate_instant_ack(self, intent: IntentResult) -> str:
        """
        Generate instant acknowledgment for long tasks.
        
        Must return within 500ms. Uses templates for speed,
        falls back to LLM only for custom cases.
        """
        # Try template-based ack first (fastest)
        if intent.intent_type == "search":
            return ACK_TEMPLATES["search"]
        
        if intent.intent_type == "complex":
            return ACK_TEMPLATES["complex"]
        
        if intent.skill_id:
            # Check for common skill actions
            for keyword, action in ACK_ACTIONS.items():
                if keyword in intent.skill_id.lower():
                    return ACK_TEMPLATES["skill"].format(action=action)
            return ACK_TEMPLATES["skill"].format(action="handle that")
        
        if intent.mcp_name:
            return ACK_TEMPLATES["mcp"].format(tool=intent.mcp_name)
        
        return ACK_TEMPLATES["default"]

    async def _execute_skill(
        self,
        session,
        context: dict,
        intent: IntentResult
    ) -> str:
        """Execute a skill and return the result."""
        if not intent.skill_id:
            return ""
        
        try:
            result = await self.skill_runner.execute(
                skill_id=intent.skill_id,
                params=intent.mcp_params,
                context={
                    "user_id": getattr(session, "user_id", None),
                    "session_id": getattr(session, "session_id", None),
                    "user_message": context.get("current_input", ""),
                },
            )
            if isinstance(result, dict) and not result.get("success", True):
                logger.warning(
                    "Skill execution failed for %s: %s",
                    intent.skill_id,
                    result.get("error"),
                )
                return "I couldn't complete that request right now."
            if isinstance(result, dict) and "result" in result:
                return str(result["result"])
            return str(result)
        except Exception as e:
            logger.error("Skill execution failed: %s", e, exc_info=True)
            return "I couldn't complete that request right now."

    async def _execute_mcp(
        self,
        session,
        context: dict,
        intent: IntentResult
    ) -> str:
        """Execute an MCP tool and return the result."""
        if not intent.mcp_name:
            return ""
        
        try:
            result = await self.mcp_runner.execute(
                tool_name=intent.mcp_name,
                params=intent.mcp_params,
                context={
                    "user_id": getattr(session, "user_id", None),
                    "session_id": getattr(session, "session_id", None),
                },
            )
            if isinstance(result, dict) and not result.get("success", True):
                logger.warning(
                    "MCP execution failed for %s: %s",
                    intent.mcp_name,
                    result.get("error"),
                )
                return "I couldn't complete that tool request right now."
            if isinstance(result, dict) and "result" in result:
                return str(result["result"])
            if isinstance(result, dict) and "data" in result:
                return str(result["data"])
            return str(result)
        except Exception as e:
            logger.error("Tool execution failed: %s", e, exc_info=True)
            return "I couldn't complete that tool request right now."

    async def _execute_search(
        self,
        session,
        context: dict,
        text: str,
        intent: IntentResult
    ) -> str:
        """Execute a search query and return results."""
        try:
            agent_context = SimpleNamespace(
                user_message=text,
                metadata={},
                user_id=getattr(session, "user_id", None),
                session_id=getattr(session, "session_id", None),
                history=context.get("conversation_window", []),
            )
            result = await self.search_agent.run(agent_context)
            return getattr(result, "response_text", None) or str(result)
        except Exception as e:
            logger.error("Search execution failed: %s", e, exc_info=True)
            return "I couldn't complete that search right now."

    async def _handle_complex_task(
        self,
        session,
        context: dict,
        text: str,
        intent: IntentResult
    ) -> dict:
        """
        Handle complex multi-step tasks.
        
        Uses parallel agent execution where possible.
        """
        # Generate ack immediately
        ack = await self._generate_instant_ack(intent)
        
        # Run task agent and memory agent in parallel
        task_coro = self.task_agent.run(
            session=session,
            task=text,
            context=context
        )
        
        memory_coro = self.memory_agent.process_turn(
            session=session,
            user_text=text,
            response=None,
        )
        
        # Execute in parallel
        results = await asyncio.gather(
            task_coro,
            memory_coro,
            return_exceptions=True
        )
        
        task_result = results[0]
        if isinstance(task_result, Exception):
            task_result = f"Task failed: {str(task_result)}"
        
        # Format the result
        formatted = await self.format_result(session, str(task_result))
        
        return {"ack": ack, "result": formatted}

    async def format_result(self, session, result: str) -> str:
        """
        Format raw result into natural language response.
        
        Takes output from skill/MCP/agent and makes it conversational.
        """
        if not result or len(result.strip()) == 0:
            return "Done."
        
        # If result is already natural language and short, return as-is
        if len(result) < 200 and not result.startswith("{"):
            return result
        
        # For longer or structured results, use LLM to format
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": f"""Format this result naturally for the user. Be concise but helpful.

Raw result:
{result[:2000]}

Provide a natural, conversational response:"""
            }
        ]
        
        try:
            formatted = await self.llm_router.call(
                user_id=session.user_id,
                task_type="orchestrate",
                messages=messages,
                max_tokens=500
            )
            return formatted
        except Exception:
            # Return raw result if formatting fails
            return result[:500] if len(result) > 500 else result

    async def _background_memory_update(
        self,
        session,
        user_input: str,
        response: str | None
    ) -> None:
        """
        Update memory in background (non-blocking).
        
        Called after each turn to update conversation memory
        and extract any important information.
        """
        try:
            await self.memory_agent.process_turn(
                session=session,
                user_text=user_input,
                response=response,
                context={}
            )
        except Exception:
            # Memory updates should never block or fail the main flow
            pass

    async def get_status(self) -> dict:
        """Get orchestrator status for health checks."""
        return {
            "status": "healthy",
            "components": {
                "llm_router": "connected",
                "task_agent": "ready",
                "search_agent": "ready", 
                "memory_agent": "ready",
                "skill_runner": "ready",
                "mcp_runner": "ready"
            }
        }