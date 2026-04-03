# =============================================================================
# server/core/context_builder.py — Dynamic Context Assembly (User-Scoped)
# =============================================================================

from __future__ import annotations

import re
from datetime import date
from typing import Any

from server.memory.vector_store import VectorStore
from server.memory.sqlite_store import SQLiteStore
from server.memory.embedder import Embedder
from server.auth.models import UserAccount


HIDE_FROM_NON_OWNER = [
    "user_private_memories", "email_content", "calendar_details",
    "financial_data", "reminders",
]

TONE_MAP = {
    "account_owner": "casual, personalized, full context",
    "known_contact": "warm, context from relationship history",
    "guest": "polite, neutral, minimal context",
    "unknown": "friendly but cautious",
}

TOKEN_BUDGETS = {
    "simple": 2500,
    "with_memory": 3000,
    "complex": 4000,
    "meeting": 3500,
}

# Simple heuristic patterns that hint at temporal references in user input
_TIME_REFERENCE_PATTERN = re.compile(
    r"\b(yesterday|today|tomorrow|last\s+week|next\s+week|last\s+month|"
    r"next\s+month|ago|morning|evening|night|monday|tuesday|wednesday|"
    r"thursday|friday|saturday|sunday|january|february|march|april|may|"
    r"june|july|august|september|october|november|december|\d{1,2}/\d{1,2}|"
    r"\d{4}-\d{2}-\d{2})\b",
    re.IGNORECASE,
)


class ContextBuilder:
    """Assembles the full LLM input context for every conversational turn.

    The builder gathers data from multiple sources — user profile, persona
    mapping, injected flags, vector-searched memories, skill/MCP registries,
    and the rolling conversation window — then trims everything to fit
    within a token budget so the model always receives a well-structured,
    priority-ordered prompt.
    """

    def __init__(
        self,
        vector_store: VectorStore,
        sqlite_store: SQLiteStore,
        embedder: Embedder,
        skill_registry: dict,
        mcp_registry: dict,
    ):
        self.vector_store = vector_store
        self.sqlite_store = sqlite_store
        self.embedder = embedder
        self.skill_registry = skill_registry
        self.mcp_registry = mcp_registry

    # --------------------------------------------------------------------- #
    # Main entry point
    # --------------------------------------------------------------------- #
    async def build(self, session, text: str, speaker_id: str) -> dict:
        """Assemble the full context dict for a single LLM turn.

        Parameters
        ----------
        session : Session
            The active user session carrying working memory, user_id,
            system prompt, flags, persona mappings, and task state.
        text : str
            The current user (or speaker) input to respond to.
        speaker_id : str
            Identifies *who* is speaking — may or may not be the account
            owner.

        Returns
        -------
        dict
            A mapping whose keys mirror the assembly order described in
            the module docstring.  Every key is always present (some may
            hold an empty string when there is nothing to inject).
        """

        # ---- 1. Load user profile -------------------------------------------
        user: UserAccount | None = self.sqlite_store.get_user(session.user_id)
        if user is None:
            user = UserAccount(
                user_id=session.user_id,
                display_name=session.user_id,
                email="",
                password_hash="",
            )

        # ---- 2. User identity block -----------------------------------------
        user_identity_block = self._build_user_identity_block(user)

        # ---- 3. Active persona context --------------------------------------
        is_owner = speaker_id == session.user_id
        persona = self._resolve_persona(session, speaker_id, is_owner)
        persona_block = self._build_persona_block(persona)

        # ---- 4. Injected flags -----------------------------------------------
        flags: list[dict] = self._collect_flags(session, is_owner)
        flags_block = self._build_flags_block(flags)

        # ---- 5. Relevant memories --------------------------------------------
        memories = await self._retrieve_memories(session, text, is_owner)
        memories_block = self._build_memories_block(memories)

        # ---- 6. Skill registry summary ---------------------------------------
        skill_summary = self._build_skill_summary()

        # ---- 7. MCP registry summary -----------------------------------------
        mcp_summary = self._build_mcp_summary(session)

        # ---- 8. Conversation window ------------------------------------------
        conversation_window = self._get_conversation_window(session)

        # ---- 8b. Recent article context --------------------------------------
        reading_context = self._build_reading_context(session)

        # ---- 9. Determine budget & complexity --------------------------------
        budget = self._determine_budget(session, memories)

        # ---- 10. Assemble & trim ---------------------------------------------
        context: dict[str, Any] = {
            "system_prompt": getattr(session, "system_prompt", ""),
            "user_identity": user_identity_block,
            "persona": persona_block,
            "flags": flags_block,
            "memories": memories_block,
            "skill_summary": skill_summary,
            "mcp_summary": mcp_summary,
            "conversation_window": conversation_window,
            "reading_context": reading_context,
            "current_input": text,
            # Metadata carried alongside for downstream consumers
            "_speaker_id": speaker_id,
            "_is_owner": is_owner,
            "_tone": persona.get("tone", TONE_MAP.get("unknown", "")),
            "_raw_memories": memories,
        }

        context = self._trim_to_budget(context, budget)
        return context

    # --------------------------------------------------------------------- #
    # Token estimation
    # --------------------------------------------------------------------- #
    def _estimate_tokens(self, text: str) -> int:
        """Rough token estimate — 1 token ≈ 4 characters."""
        if not text:
            return 0
        return len(text) // 4

    # --------------------------------------------------------------------- #
    # Budget determination
    # --------------------------------------------------------------------- #
    def _determine_budget(self, session, memories: list) -> int:
        """Pick token budget based on current task complexity."""

        # Meeting mode gets its own budget
        if getattr(session, "meeting_mode", False):
            return TOKEN_BUDGETS["meeting"]

        # If there is a running skill / task → complex
        task_state = getattr(session, "task_state", None)
        if isinstance(task_state, dict) and task_state.get("status") == "running":
            return TOKEN_BUDGETS["complex"]

        # If we retrieved memories → with_memory
        if memories:
            return TOKEN_BUDGETS["with_memory"]

        return TOKEN_BUDGETS["simple"]

    # --------------------------------------------------------------------- #
    # Trimming
    # --------------------------------------------------------------------- #
    def _trim_to_budget(self, context: dict, budget: int) -> dict:
        """Apply priority-based trimming so total tokens stay within *budget*.

        Priority (never trimmed):
          • system_prompt
          • user_identity
          • current_input

        Trimming order:
          1. Drop oldest conversation turns first.
          2. Reduce retrieved memories from 5 → 3 → 1 → 0.
          3. Drop flags, skill_summary, mcp_summary only as last resort.
        """

        def _total(ctx: dict) -> int:
            total = 0
            for key, value in ctx.items():
                if key.startswith("_"):
                    continue
                if isinstance(value, str):
                    total += self._estimate_tokens(value)
                elif isinstance(value, list):
                    # conversation_window is a list of turn strings
                    total += sum(self._estimate_tokens(str(t)) for t in value)
            return total

        # Nothing to do if already within budget
        if _total(context) <= budget:
            return context

        # --- Step 1: trim conversation window (drop oldest first) -----------
        window = context.get("conversation_window", [])
        while window and _total(context) > budget:
            window.pop(0)
        context["conversation_window"] = window

        if _total(context) <= budget:
            return context

        # --- Step 2: reduce memories ----------------------------------------
        raw_memories: list = context.get("_raw_memories", [])
        for target_count in (3, 1, 0):
            if len(raw_memories) > target_count:
                raw_memories = raw_memories[:target_count]
                context["_raw_memories"] = raw_memories
                context["memories"] = self._build_memories_block(raw_memories)
            if _total(context) <= budget:
                return context

        # --- Step 3: drop optional sections as last resort ------------------
        for optional_key in ("flags", "mcp_summary", "skill_summary", "persona", "reading_context"):
            if _total(context) <= budget:
                return context
            context[optional_key] = ""

        return context

    # --------------------------------------------------------------------- #
    # Block builders
    # --------------------------------------------------------------------- #
    def _build_user_identity_block(self, user: UserAccount) -> str:
        """Format the authenticated user's profile into a compact text block.

        Example output:
            User: Rahul | CS student | Goals: Build Vayumi, Learn AI agents
            | Tone: casual and direct | Language: en
        """
        parts: list[str] = []

        name = getattr(user, "name", None) or getattr(user, "display_name", None) or "Unknown"
        parts.append(f"User: {name}")

        bio = getattr(user, "bio", None) or getattr(user, "description", None)
        if bio:
            parts.append(bio)

        goals = getattr(user, "goals", None)
        if goals:
            if isinstance(goals, list):
                goals = ", ".join(goals)
            parts.append(f"Goals: {goals}")

        tone = getattr(user, "tone", None)
        if tone:
            parts.append(f"Tone: {tone}")

        language = getattr(user, "language", None) or "en"
        parts.append(f"Language: {language}")

        return " | ".join(parts)

    def _build_persona_block(self, persona: dict) -> str:
        """Format a persona dict into a compact text block.

        Example output:
            Speaker: Rahul (account_owner) | Tone: casual and direct
            | Context: CS student, building Vayumi, Uses Groq
        """
        if not persona:
            return ""

        parts: list[str] = []

        speaker_name = persona.get("name", "Unknown")
        role = persona.get("role", "unknown")
        parts.append(f"Speaker: {speaker_name} ({role})")

        tone = persona.get("tone")
        if tone:
            parts.append(f"Tone: {tone}")

        ctx = persona.get("context")
        if ctx:
            if isinstance(ctx, list):
                ctx = ", ".join(ctx)
            parts.append(f"Context: {ctx}")

        return " | ".join(parts)

    def _build_flags_block(self, flags: list[dict]) -> str:
        """Format injected flags into newline-separated flag lines.

        Example output:
            [FLAG] New email from Prof. Sharma: 'Project Deadline Update'
            [FLAG] Reminder: Submit assignment by 11:59 PM
        """
        if not flags:
            return ""

        lines: list[str] = []
        for flag in flags:
            summary = flag.get("summary") or flag.get("text") or flag.get("message", "")
            flag_type = flag.get("type", "event")
            if summary:
                lines.append(f"[FLAG:{flag_type.upper()}] {summary}")
        return "\n".join(lines)

    def _build_memories_block(self, memories: list) -> str:
        """Format retrieved memories into a bulleted list.

        Each memory is expected to be a dict (or object) with at least
        ``text`` and optionally ``timestamp`` / ``age`` fields.

        Example output:
            - 2 days ago: Discussed Vayumi memory architecture
            - 1 week ago: Reviewed Groq API rate limits
        """
        if not memories:
            return ""

        lines: list[str] = []
        for mem in memories:
            if isinstance(mem, dict):
                text = mem.get("text", "")
                age = mem.get("age") or mem.get("timestamp", "")
            else:
                # Support object-style memories with attributes
                text = getattr(mem, "text", str(mem))
                age = getattr(mem, "age", "") or getattr(mem, "timestamp", "")

            prefix = f"{age}: " if age else ""
            lines.append(f"- {prefix}{text}")

        return "\n".join(lines)

    # --------------------------------------------------------------------- #
    # Skill / MCP summaries
    # --------------------------------------------------------------------- #
    def _build_skill_summary(self) -> str:
        """One-line-per-skill summary of the skill registry.

        Only names and short descriptions are emitted — no detailed
        schemas — to keep the token footprint around ~100 tokens.
        """
        skills = self.skill_registry.get("skills", []) if isinstance(self.skill_registry, dict) else []
        if not skills:
            return ""

        lines: list[str] = []
        for skill in skills:
            if not isinstance(skill, dict):
                continue
            skill_id = skill.get("id", "unknown")
            desc = skill.get("description", "")
            lines.append(f"- {skill_id}: {desc}")
        return "Available skills:\n" + "\n".join(lines)

    def _build_mcp_summary(self, session) -> str:
        """List the MCP integrations enabled for this user's session."""
        if not self.mcp_registry:
            return ""

        enabled = set(getattr(session, "enabled_mcps", None) or [])
        always_on = self.mcp_registry.get("always_on", []) if isinstance(self.mcp_registry, dict) else []
        on_demand = self.mcp_registry.get("on_demand", []) if isinstance(self.mcp_registry, dict) else []

        lines: list[str] = []
        for mcp in always_on:
            if not isinstance(mcp, dict):
                continue
            name = mcp.get("name")
            if not name:
                continue
            desc = mcp.get("description", "")
            lines.append(f"- {name}: {desc}")

        for mcp in on_demand:
            if not isinstance(mcp, dict):
                continue
            name = mcp.get("name")
            if not name or name not in enabled:
                continue
            desc = mcp.get("description", "")
            lines.append(f"- {name}: {desc}")

        if not lines:
            return ""
        return "Enabled MCPs:\n" + "\n".join(lines)

    # --------------------------------------------------------------------- #
    # Conversation window
    # --------------------------------------------------------------------- #
    def _get_conversation_window(self, session) -> list[str]:
        """Pull the recent conversation turns from the session's working
        memory.  Returns a list of formatted turn strings.
        """
        working_memory = getattr(session, "working_memory", None)
        if working_memory is None:
            return []

        # working_memory may be a list of dicts with role/content or plain
        # strings — normalise to list[str].
        turns: list[str] = []
        if isinstance(working_memory, list):
            for entry in working_memory:
                if isinstance(entry, dict):
                    role = entry.get("role", "user")
                    content = entry.get("content") or entry.get("text", "")
                    turns.append(f"{role}: {content}")
                else:
                    turns.append(str(entry))
        return turns

    def _build_reading_context(self, session) -> str:
        """Return the most recent URL/article context if one exists."""
        reading_context = getattr(session, "last_read_context", None)
        if not isinstance(reading_context, dict):
            return ""

        parts: list[str] = ["Recent article context:"]
        title = reading_context.get("title")
        url = reading_context.get("url")
        author = reading_context.get("author")
        summary = reading_context.get("summary")
        excerpt = reading_context.get("excerpt")

        if title:
            parts.append(f"Title: {title}")
        if url:
            parts.append(f"URL: {url}")
        if author:
            parts.append(f"Author: {author}")
        if summary:
            parts.append(f"Summary: {summary}")
        if excerpt:
            parts.append(f"Excerpt: {excerpt[:4000]}")

        return "\n".join(parts)

    # --------------------------------------------------------------------- #
    # Persona resolution
    # --------------------------------------------------------------------- #
    def _resolve_persona(self, session, speaker_id: str, is_owner: bool) -> dict:
        """Build a persona dict for the current speaker."""

        if is_owner:
            # Owner persona may be stored directly on the session or profile
            owner_persona = getattr(session, "owner_persona", None)
            if owner_persona and isinstance(owner_persona, dict):
                persona = dict(owner_persona)
            else:
                persona = {"name": getattr(session, "user_name", "Owner")}
            persona.setdefault("role", "account_owner")
            persona.setdefault("tone", TONE_MAP["account_owner"])
            return persona

        # Non-owner — look up via persona mapping on session
        persona_map: dict = getattr(session, "persona_map", {})
        persona = persona_map.get(speaker_id, {})
        if not persona:
            # Completely unknown speaker
            return {
                "name": speaker_id or "Unknown",
                "role": "unknown",
                "tone": TONE_MAP["unknown"],
            }

        persona = dict(persona)  # shallow copy
        role = persona.get("role", "guest")
        persona.setdefault("tone", TONE_MAP.get(role, TONE_MAP["unknown"]))
        return persona

    # --------------------------------------------------------------------- #
    # Flag collection
    # --------------------------------------------------------------------- #
    def _collect_flags(self, session, is_owner: bool) -> list[dict]:
        """Gather injected flags from the session, respecting privacy rules."""

        raw_flags: list[dict] = getattr(session, "flags", None) or []
        if not raw_flags:
            # Also try a flag_store attribute
            flag_store = getattr(session, "flag_store", None)
            if flag_store is not None:
                if callable(getattr(flag_store, "get_pending", None)):
                    raw_flags = flag_store.get_pending()
                elif isinstance(flag_store, list):
                    raw_flags = flag_store

        if is_owner:
            return list(raw_flags)

        # Non-owner: filter out private flag categories
        filtered: list[dict] = []
        for flag in raw_flags:
            category = flag.get("category") or flag.get("type", "")
            if category in HIDE_FROM_NON_OWNER:
                continue
            filtered.append(flag)
        return filtered

    # --------------------------------------------------------------------- #
    # Memory retrieval
    # --------------------------------------------------------------------- #
    async def _retrieve_memories(
        self, session, text: str, is_owner: bool
    ) -> list:
        """Retrieve relevant memories via vector similarity and, when the
        user input contains temporal references, also via date-based SQLite
        lookup.  Results are filtered for privacy when the speaker is not
        the account owner.
        """

        # Embed the current input
        embedding = self.embedder.embed(text)

        # Vector search — scoped to the session's user
        vector_results: list = await self.vector_store.query(
            embedding=embedding,
            user_id=session.user_id,
            top_k=5,
        )

        # If the text contains temporal cues, augment with date-based search
        if _TIME_REFERENCE_PATTERN.search(text):
            # SQLite store exposes query_by_date(user_id, date_str).
            # Use explicit ISO date if present in input, otherwise fall back to today.
            match = re.search(r"\b\d{4}-\d{2}-\d{2}\b", text)
            query_date = match.group(0) if match else date.today().isoformat()
            date_results = self.sqlite_store.query_by_date(
                session.user_id,
                query_date,
            )
            if date_results:
                # Merge, avoiding duplicates (by text content)
                existing_texts = {
                    (m.get("text") if isinstance(m, dict) else getattr(m, "text", ""))
                    for m in vector_results
                }
                for mem in date_results:
                    mem_text = (
                        mem.get("text") if isinstance(mem, dict)
                        else getattr(mem, "text", "")
                    )
                    if mem_text not in existing_texts:
                        vector_results.append(mem)

        # Privacy: strip private memories when the speaker is not the owner
        if not is_owner:
            vector_results = self._filter_private_memories(vector_results)

        return vector_results

    def _filter_private_memories(self, memories: list) -> list:
        """Remove memories whose category falls within HIDE_FROM_NON_OWNER."""
        filtered: list = []
        for mem in memories:
            if isinstance(mem, dict):
                cat = mem.get("category", "")
            else:
                cat = getattr(mem, "category", "")
            if cat in HIDE_FROM_NON_OWNER:
                continue
            filtered.append(mem)
        return filtered