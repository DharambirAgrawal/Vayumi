# =============================================================================
# server/agents/memory_agent.py — Memory Agent (Async Background)
# =============================================================================

from __future__ import annotations

import logging
import re
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from server.agents.base_agent import BaseAgent, AgentContext, AgentResult
from server.llm.router import LLMRouter
from server.memory.vector_store import VectorStore
from server.memory.sqlite_store import SQLiteStore
from server.memory.embedder import Embedder

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PERSONA_MEMORY_ACCESS: dict[str, str] = {
    "account_owner": "all",
    "known_contact": "shared_only",
    "guest": "none",
}

SUMMARIZE_EVERY_N_TURNS: int = 15

# Number of top results to retrieve from vector search
RETRIEVAL_TOP_K: int = 5

# LLM model choices
FAST_MODEL: str = "llama-3.1-8b-instant"
SUMMARIZATION_MAX_TOKENS: int = 300
TURN_SUMMARY_MAX_TOKENS: int = 150

# ---------------------------------------------------------------------------
# Keyword / pattern banks for heuristic classification
# ---------------------------------------------------------------------------

_REMEMBER_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\bremember\s+(that|this|to)\b", re.IGNORECASE),
    re.compile(r"\bdon'?t\s+forget\b", re.IGNORECASE),
    re.compile(r"\bkeep\s+in\s+mind\b", re.IGNORECASE),
    re.compile(r"\bnote\s+(that|this|down)\b", re.IGNORECASE),
    re.compile(r"\bsave\s+(this|that)\b", re.IGNORECASE),
    re.compile(r"\bmake\s+a\s+note\b", re.IGNORECASE),
]

_DATE_TIME_PATTERNS: list[re.Pattern[str]] = [
    re.compile(
        r"\b(january|february|march|april|may|june|july|august|"
        r"september|october|november|december)\s+\d{1,2}", re.IGNORECASE,
    ),
    re.compile(r"\b\d{1,2}/\d{1,2}(/\d{2,4})?\b"),
    re.compile(r"\b\d{4}-\d{2}-\d{2}\b"),
    re.compile(r"\b(today|tomorrow|yesterday|next\s+week|next\s+month)\b", re.IGNORECASE),
    re.compile(r"\b(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b", re.IGNORECASE),
    re.compile(r"\b\d{1,2}\s*(am|pm|AM|PM)\b"),
    re.compile(r"\b(morning|afternoon|evening|tonight)\b", re.IGNORECASE),
    re.compile(r"\bin\s+\d+\s+(minutes?|hours?|days?|weeks?|months?)\b", re.IGNORECASE),
]

_ACTION_ITEM_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\b(need\s+to|have\s+to|should|must|gonna|going\s+to)\b", re.IGNORECASE),
    re.compile(r"\b(todo|to-do|task|deadline|due\s+date)\b", re.IGNORECASE),
    re.compile(r"\b(remind\s+me|set\s+a\s+reminder|alert\s+me)\b", re.IGNORECASE),
    re.compile(r"\b(schedule|book|reserve|arrange|plan)\b", re.IGNORECASE),
    re.compile(r"\b(call|email|text|message|contact|reach\s+out)\b", re.IGNORECASE),
]

_DECISION_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\b(decided|decision|let'?s\s+go\s+with|we'?ll\s+do)\b", re.IGNORECASE),
    re.compile(r"\b(agreed|agreement|confirmed|final\s+answer)\b", re.IGNORECASE),
    re.compile(r"\b(choose|chose|picked|selected|went\s+with)\b", re.IGNORECASE),
]

_EMOTIONAL_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\b(love|hate|afraid|worried|excited|nervous|happy|sad)\b", re.IGNORECASE),
    re.compile(r"\b(proud|frustrated|angry|grateful|thankful|anxious)\b", re.IGNORECASE),
    re.compile(r"\b(amazing|terrible|horrible|wonderful|incredible)\b", re.IGNORECASE),
    re.compile(r"\b(important\s+to\s+me|means\s+a\s+lot|care\s+about)\b", re.IGNORECASE),
]

# Name detection: simple proper-noun heuristic (capitalized words not at
# sentence start that aren't common English words).  A production system
# would use an NER model; this serves as a fast first-pass filter.
_PROPER_NOUN_PATTERN: re.Pattern[str] = re.compile(
    r"(?<!\.\s)(?<!\A)\b([A-Z][a-z]{2,})\b"
)

_COMMON_CAPITALIZED: set[str] = {
    "I", "The", "This", "That", "What", "When", "Where", "Why", "How",
    "Yes", "No", "Hey", "Hi", "Hello", "Sure", "Thanks", "Okay", "Ok",
    "Also", "But", "And", "Just", "Well", "So", "Really", "Very",
    "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday",
    "January", "February", "March", "April", "May", "June", "July",
    "August", "September", "October", "November", "December",
}

_SENSITIVITY_PRIVATE_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\b(password|ssn|social\s+security|credit\s+card)\b", re.IGNORECASE),
    re.compile(r"\b(bank\s+account|account\s+number|routing\s+number)\b", re.IGNORECASE),
    re.compile(r"\b(medical|diagnosis|prescription|health\s+record)\b", re.IGNORECASE),
    re.compile(r"\b(salary|income|tax|financial)\b", re.IGNORECASE),
    re.compile(r"\b(private|confidential|secret|personal)\b", re.IGNORECASE),
    re.compile(r"\b(address|phone\s+number|email\s+address)\b", re.IGNORECASE),
]

_SENSITIVITY_SHARED_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\b(meeting|team|project|we\s+decided|group)\b", re.IGNORECASE),
    re.compile(r"\b(shared|everyone|together|collaborate)\b", re.IGNORECASE),
    re.compile(r"\b(announcement|update\s+for|let\s+everyone\s+know)\b", re.IGNORECASE),
]

# ---------------------------------------------------------------------------
# Structured-data extraction patterns (for SQLite side-storage)
# ---------------------------------------------------------------------------
_REMINDER_PATTERN: re.Pattern[str] = re.compile(
    r"\bremind\s+me\s+(to\s+)?(.+?)(?:\s+(?:at|on|by|in|before)\s+(.+))?$",
    re.IGNORECASE,
)

_PERSON_MENTION_PATTERN: re.Pattern[str] = re.compile(
    r"\b([A-Z][a-z]{2,}(?:\s+[A-Z][a-z]{2,})?)\b"
)


# ===========================================================================
# MemoryAgent
# ===========================================================================
class MemoryAgent(BaseAgent):
    """Reads and writes memory.  Retrieval is synchronous (called by the
    context builder); writing is asynchronous (background task after the
    user-facing response has already been sent)."""

    # ------------------------------------------------------------------ init
    def __init__(
        self,
        llm_router: LLMRouter,
        vector_store: VectorStore,
        sqlite_store: SQLiteStore,
        embedder: Embedder,
    ) -> None:
        self.llm_router = llm_router
        self.vector_store = vector_store
        self.sqlite_store = sqlite_store
        self.embedder = embedder

        # session_id → turn count since last chunk summarisation
        self._turn_counter: dict[str, int] = defaultdict(int)

        # session_id → list of recent turns awaiting summarisation
        self._turn_buffer: dict[str, list[dict[str, Any]]] = defaultdict(list)

    # =========================================================================
    # RETRIEVAL PATH — called by context_builder
    # =========================================================================
    async def run(self, context: AgentContext) -> AgentResult:
        """Retrieve relevant memories for the current turn.

        Steps:
          1. Determine the caller's memory-access level from persona role.
          2. Embed ``context.input_text``.
          3. Query the vector store with user_id filter and top-k.
          4. If time references are present → also query SQLite by date.
          5. Filter results by sensitivity vs. access level.
          6. Format and return.
        """
        user_id: str = context.user_id
        input_text: str = context.input_text
        persona: dict[str, Any] = getattr(context, "persona", {}) or {}
        role: str = persona.get("role", "guest")
        access_level: str = PERSONA_MEMORY_ACCESS.get(role, "none")

        # Guests get no memories
        if access_level == "none":
            return AgentResult(
                agent_name="memory_agent",
                success=True,
                data={"memories": [], "formatted": ""},
            )

        # --- Step 1: Embed the query ---
        try:
            query_embedding = self.embedder.embed(input_text)
        except Exception:
            logger.warning("Embedding failed for memory retrieval", exc_info=True)
            return AgentResult(
                agent_name="memory_agent",
                success=False,
                data={"memories": [], "formatted": ""},
                error="embedding_failed",
            )

        # --- Step 2: Vector search ---
        where_filter: dict[str, Any] = {"user_id": user_id}
        try:
            vector_results: list[dict[str, Any]] = await self.vector_store.query(
                embedding=query_embedding,
                where=where_filter,
                top_k=RETRIEVAL_TOP_K,
            )
        except Exception:
            logger.warning("Vector store query failed", exc_info=True)
            vector_results = []

        # --- Step 3: Date-based SQLite lookup if time references found ---
        sqlite_results: list[dict[str, Any]] = []
        if self._has_time_reference(input_text):
            try:
                sqlite_results = await self._query_sqlite_by_date(user_id, input_text)
            except Exception:
                logger.debug("SQLite date query failed", exc_info=True)

        # --- Step 4: Merge & deduplicate ---
        seen_ids: set[str] = set()
        merged: list[dict[str, Any]] = []
        for mem in vector_results + sqlite_results:
            mem_id = mem.get("id", "")
            if mem_id in seen_ids:
                continue
            seen_ids.add(mem_id)
            merged.append(mem)

        # --- Step 5: Filter by sensitivity ---
        filtered = self._filter_by_access(merged, access_level)

        # --- Step 6: Format for LLM injection ---
        formatted = self._format_memories(filtered)

        logger.debug(
            "Memory retrieval: %d vector + %d sqlite → %d merged → %d after access filter",
            len(vector_results),
            len(sqlite_results),
            len(merged),
            len(filtered),
        )

        return AgentResult(
            agent_name="memory_agent",
            success=True,
            data={"memories": filtered, "formatted": formatted},
        )

    # =========================================================================
    # WRITE PATH — called as background task after response
    # =========================================================================
    async def process_turn(
        self,
        session: Any,
        user_text: str,
        response: Any,
    ) -> None:
        """Decide whether to memorise the turn and, if so, store it.

        This method is designed to run as a **background task** and must
        never raise — all exceptions are caught and logged.

        Parameters
        ----------
        session :
            Active session object with at least ``.user_id``, ``.session_id``,
            and optionally ``.speaker_id``.
        user_text :
            The raw user utterance for this turn.
        response :
            The assistant's response.  May be a string, or an object with a
            ``.text`` attribute.
        """
        try:
            await self._process_turn_inner(session, user_text, response)
        except Exception:
            logger.error("MemoryAgent.process_turn failed", exc_info=True)

    async def _process_turn_inner(
        self,
        session: Any,
        user_text: str,
        response: Any,
    ) -> None:
        user_id: str = session.user_id
        session_id: str = session.session_id
        speaker_id: str = getattr(session, "speaker_id", "unknown")
        response_text = response if isinstance(response, str) else getattr(response, "text", str(response))
        now = datetime.now(timezone.utc)

        # Always buffer the turn (for chunk summarisation)
        turn_record: dict[str, Any] = {
            "user_text": user_text,
            "response_text": response_text,
            "speaker_id": speaker_id,
            "timestamp": now.isoformat(),
        }
        self._turn_buffer[session_id].append(turn_record)
        self._turn_counter[session_id] += 1

        # --- Step 1: Is this turn memorable on its own? ---
        if self._is_memorable(user_text, response_text):
            await self._store_single_turn(
                user_id=user_id,
                speaker_id=speaker_id,
                user_text=user_text,
                response_text=response_text,
                timestamp=now,
            )

        # --- Step 2: Extract structured data (reminders, people) ---
        await self._extract_and_store_structured(user_id, user_text, now)

        # --- Step 3: Chunk summarisation threshold ---
        if self._turn_counter[session_id] >= SUMMARIZE_EVERY_N_TURNS:
            turns_to_summarise = list(self._turn_buffer[session_id])
            self._turn_buffer[session_id].clear()
            self._turn_counter[session_id] = 0
            await self._summarize_chunk(turns_to_summarise, user_id)

    # ------------------------------------------------------------------
    # Memorability heuristic
    # ------------------------------------------------------------------
    def _is_memorable(self, text: str, response: str) -> bool:
        """Return ``True`` if the turn warrants individual storage.

        A turn is memorable if it contains any of:
          - An explicit "remember" request
          - Names / people mentions
          - Dates or times
          - Action items / tasks
          - Important decisions
          - Emotional significance
        """
        combined = f"{text} {response}"

        # 1. Explicit remember request
        if any(p.search(text) for p in _REMEMBER_PATTERNS):
            return True

        # 2. Dates / times
        if any(p.search(combined) for p in _DATE_TIME_PATTERNS):
            return True

        # 3. Action items
        if any(p.search(text) for p in _ACTION_ITEM_PATTERNS):
            return True

        # 4. Decisions
        if any(p.search(combined) for p in _DECISION_PATTERNS):
            return True

        # 5. Emotional significance
        if any(p.search(text) for p in _EMOTIONAL_PATTERNS):
            return True

        # 6. People mentioned (proper nouns not in common set)
        proper_nouns = _PROPER_NOUN_PATTERN.findall(combined)
        novel_names = [n for n in proper_nouns if n not in _COMMON_CAPITALIZED]
        if novel_names:
            return True

        return False

    # ------------------------------------------------------------------
    # Sensitivity classification
    # ------------------------------------------------------------------
    def _classify_sensitivity(self, content: str) -> str:
        """Classify memory sensitivity: ``"private"`` | ``"shared"`` | ``"public"``.

        Default is ``"private"`` (safe default).  Shared keywords promote to
        ``"shared"``.  We never auto-classify as ``"public"`` — that requires
        explicit user action.
        """
        # Check for strongly private indicators first
        if any(p.search(content) for p in _SENSITIVITY_PRIVATE_PATTERNS):
            return "private"

        # Check for shared indicators
        if any(p.search(content) for p in _SENSITIVITY_SHARED_PATTERNS):
            return "shared"

        # Safe default
        return "private"

    # ------------------------------------------------------------------
    # Chunk summarisation
    # ------------------------------------------------------------------
    async def _summarize_chunk(
        self,
        turns: list[dict[str, Any]],
        user_id: str,
    ) -> None:
        """Summarise a batch of conversation turns into one episodic memory.

        Uses the fast LLM for summarisation, then embeds and stores the
        resulting summary.
        """
        if not turns:
            return

        # Build a transcript for the LLM
        transcript_lines: list[str] = []
        for t in turns:
            transcript_lines.append(f"User ({t.get('speaker_id', '?')}): {t['user_text']}")
            transcript_lines.append(f"Assistant: {t['response_text']}")
        transcript = "\n".join(transcript_lines)

        # Truncate to avoid exceeding model context
        max_chars = 6000
        if len(transcript) > max_chars:
            transcript = transcript[:max_chars] + "\n... [truncated]"

        prompt = (
            "Summarize the following conversation into a concise episodic memory. "
            "Capture: key topics discussed, decisions made, action items, people "
            "mentioned, and any emotional tone. Be factual and brief.\n\n"
            f"CONVERSATION:\n{transcript}\n\n"
            "SUMMARY:"
        )

        try:
            summary_response = await self.llm_router.generate(
                prompt=prompt,
                model=FAST_MODEL,
                max_tokens=SUMMARIZATION_MAX_TOKENS,
                temperature=0.3,
            )
            summary_text = (
                summary_response
                if isinstance(summary_response, str)
                else getattr(summary_response, "text", str(summary_response))
            ).strip()
        except Exception:
            logger.warning("Chunk summarisation LLM call failed", exc_info=True)
            # Fallback: concatenate user texts as a crude summary
            summary_text = "Conversation covered: " + "; ".join(
                t["user_text"][:80] for t in turns[:5]
            )

        # Determine sensitivity and tags
        sensitivity = self._classify_sensitivity(summary_text)
        tags = self._extract_tags(summary_text)

        # Determine timestamp range
        first_ts = turns[0].get("timestamp", datetime.now(timezone.utc).isoformat())
        last_ts = turns[-1].get("timestamp", datetime.now(timezone.utc).isoformat())

        # Embed and store
        await self._embed_and_store(
            user_id=user_id,
            speaker_id="multi",
            content=summary_text,
            sensitivity=sensitivity,
            tags=tags,
            timestamp=first_ts,
            metadata={
                "type": "episodic_chunk",
                "turn_count": len(turns),
                "time_start": first_ts,
                "time_end": last_ts,
            },
        )

        logger.info(
            "Summarised %d turns into episodic chunk for user=%s (sensitivity=%s)",
            len(turns),
            user_id,
            sensitivity,
        )

    # =========================================================================
    # Internal helpers
    # =========================================================================

    async def _store_single_turn(
        self,
        user_id: str,
        speaker_id: str,
        user_text: str,
        response_text: str,
        timestamp: datetime,
    ) -> None:
        """Summarise and store a single memorable turn."""
        # For explicit "remember" requests, store the user text almost verbatim
        is_explicit = any(p.search(user_text) for p in _REMEMBER_PATTERNS)

        if is_explicit:
            # Strip the "remember that" prefix to get the core content
            content = user_text
            for p in _REMEMBER_PATTERNS:
                content = p.sub("", content).strip()
            if not content:
                content = user_text
            content = f"User asked to remember: {content}"
        else:
            # Quick LLM summarisation of the turn
            prompt = (
                "Summarize this exchange in one concise sentence capturing the key fact:\n"
                f"User: {user_text}\n"
                f"Assistant: {response_text}\n"
                "Summary:"
            )
            try:
                summary_resp = await self.llm_router.generate(
                    prompt=prompt,
                    model=FAST_MODEL,
                    max_tokens=TURN_SUMMARY_MAX_TOKENS,
                    temperature=0.2,
                )
                content = (
                    summary_resp
                    if isinstance(summary_resp, str)
                    else getattr(summary_resp, "text", str(summary_resp))
                ).strip()
            except Exception:
                logger.debug("Turn summarisation failed; storing raw text", exc_info=True)
                content = f"User said: {user_text[:200]}"

        sensitivity = self._classify_sensitivity(f"{user_text} {response_text}")
        tags = self._extract_tags(f"{user_text} {response_text}")

        await self._embed_and_store(
            user_id=user_id,
            speaker_id=speaker_id,
            content=content,
            sensitivity=sensitivity,
            tags=tags,
            timestamp=timestamp.isoformat(),
            metadata={"type": "single_turn", "explicit_remember": is_explicit},
        )

    async def _embed_and_store(
        self,
        user_id: str,
        speaker_id: str,
        content: str,
        sensitivity: str,
        tags: list[str],
        timestamp: str,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Embed content and persist to both vector store and SQLite.

        Returns the generated memory ID.
        """
        memory_id = str(uuid.uuid4())

        # Embed
        try:
            embedding = self.embedder.embed(content)
        except Exception:
            logger.error("Failed to embed memory content", exc_info=True)
            raise

        # Prepare metadata for vector store
        vector_metadata: dict[str, Any] = {
            "user_id": user_id,
            "speaker_id": speaker_id,
            "sensitivity": sensitivity,
            "tags": ",".join(tags) if tags else "",
            "timestamp": timestamp,
        }
        if metadata:
            vector_metadata.update(metadata)

        # Store in vector DB
        await self.vector_store.upsert(
            ids=[memory_id],
            embeddings=[embedding],
            documents=[content],
            metadatas=[vector_metadata],
        )

        # Mirror key fields in SQLite for structured queries
        await self.sqlite_store.execute(
            """
            INSERT INTO memories
                (id, user_id, speaker_id, content, embedding_id,
                 timestamp, sensitivity, tags)
            VALUES
                (:id, :user_id, :speaker_id, :content, :embedding_id,
                 :timestamp, :sensitivity, :tags)
            """,
            {
                "id": memory_id,
                "user_id": user_id,
                "speaker_id": speaker_id,
                "content": content,
                "embedding_id": memory_id,  # same id for cross-reference
                "timestamp": timestamp,
                "sensitivity": sensitivity,
                "tags": ",".join(tags),
            },
        )

        logger.debug("Stored memory %s (sensitivity=%s, tags=%s)", memory_id, sensitivity, tags)
        return memory_id

    # ------------------------------------------------------------------
    # Structured data extraction (reminders, people)
    # ------------------------------------------------------------------
    async def _extract_and_store_structured(
        self,
        user_id: str,
        user_text: str,
        timestamp: datetime,
    ) -> None:
        """Extract reminders and people mentions, storing them in SQLite."""
        # --- Reminders ---
        reminder_match = _REMINDER_PATTERN.search(user_text)
        if reminder_match:
            task = reminder_match.group(2).strip()
            time_ref = (reminder_match.group(3) or "").strip()
            try:
                await self.sqlite_store.execute(
                    """
                    INSERT INTO reminders (id, user_id, task, time_reference,
                                           created_at, status)
                    VALUES (:id, :user_id, :task, :time_reference,
                            :created_at, :status)
                    """,
                    {
                        "id": str(uuid.uuid4()),
                        "user_id": user_id,
                        "task": task,
                        "time_reference": time_ref or None,
                        "created_at": timestamp.isoformat(),
                        "status": "pending",
                    },
                )
                logger.debug("Extracted reminder: '%s' (time: %s)", task, time_ref or "none")
            except Exception:
                logger.debug("Reminder extraction/storage failed", exc_info=True)

        # --- People mentions ---
        names_found = _PERSON_MENTION_PATTERN.findall(user_text)
        novel_names = [n for n in names_found if n not in _COMMON_CAPITALIZED]
        for name in set(novel_names):
            try:
                # Upsert: update last_mentioned or insert
                existing = await self.sqlite_store.fetch_one(
                    "SELECT id FROM people_mentions WHERE user_id = :user_id AND name = :name",
                    {"user_id": user_id, "name": name},
                )
                if existing:
                    await self.sqlite_store.execute(
                        """
                        UPDATE people_mentions
                        SET mention_count = mention_count + 1,
                            last_mentioned = :ts
                        WHERE user_id = :user_id AND name = :name
                        """,
                        {"user_id": user_id, "name": name, "ts": timestamp.isoformat()},
                    )
                else:
                    await self.sqlite_store.execute(
                        """
                        INSERT INTO people_mentions
                            (id, user_id, name, mention_count,
                             first_mentioned, last_mentioned, context_snippet)
                        VALUES
                            (:id, :user_id, :name, 1,
                             :ts, :ts, :snippet)
                        """,
                        {
                            "id": str(uuid.uuid4()),
                            "user_id": user_id,
                            "name": name,
                            "ts": timestamp.isoformat(),
                            "snippet": user_text[:200],
                        },
                    )
            except Exception:
                logger.debug("People mention storage failed for '%s'", name, exc_info=True)

    # ------------------------------------------------------------------
    # Retrieval helpers
    # ------------------------------------------------------------------
    def _has_time_reference(self, text: str) -> bool:
        """Return ``True`` if ``text`` contains date/time references."""
        return any(p.search(text) for p in _DATE_TIME_PATTERNS)

    async def _query_sqlite_by_date(
        self,
        user_id: str,
        text: str,
    ) -> list[dict[str, Any]]:
        """Query SQLite memories table for temporally-relevant results.

        This is a supplementary retrieval path: when the user asks about
        something that happened "yesterday" or "last Tuesday", we query
        structured storage in addition to the vector search.
        """
        # Determine rough time window from the text
        # For a production system this would use a date parser (dateutil, etc.)
        # Here we do a simple "recent memories" heuristic: fetch the last
        # N memories sorted by timestamp descending.
        try:
            rows = await self.sqlite_store.fetch_all(
                """
                SELECT * FROM memories
                WHERE user_id = :user_id
                ORDER BY timestamp DESC
                LIMIT :limit
                """,
                {"user_id": user_id, "limit": RETRIEVAL_TOP_K},
            )
            if rows is None:
                return []
            return [dict(r) if not isinstance(r, dict) else r for r in rows]
        except Exception:
            logger.debug("SQLite date query failed", exc_info=True)
            return []

    def _filter_by_access(
        self,
        memories: list[dict[str, Any]],
        access_level: str,
    ) -> list[dict[str, Any]]:
        """Filter memories based on the caller's access level.

        Access mapping:
          - ``"all"``         → private + shared + public
          - ``"shared_only"`` → shared + public
          - ``"none"``        → nothing
        """
        if access_level == "all":
            return memories
        if access_level == "none":
            return []

        # "shared_only"
        allowed_sensitivities = {"shared", "public"}
        return [
            m for m in memories
            if m.get("sensitivity", m.get("metadata", {}).get("sensitivity", "private"))
            in allowed_sensitivities
        ]

    def _format_memories(self, memories: list[dict[str, Any]]) -> str:
        """Format retrieved memories into a string suitable for LLM injection."""
        if not memories:
            return ""

        lines: list[str] = ["[Relevant Memories]"]
        for i, mem in enumerate(memories, 1):
            content = mem.get("content", mem.get("document", ""))
            ts = mem.get("timestamp", "")
            tags = mem.get("tags", "")
            if isinstance(tags, list):
                tags = ", ".join(tags)

            header_parts = [f"Memory {i}"]
            if ts:
                # Show only the date portion for brevity
                header_parts.append(str(ts)[:10])
            if tags:
                header_parts.append(f"[{tags}]")

            lines.append(f"  {' | '.join(header_parts)}: {content}")

        return "\n".join(lines)

    def _extract_tags(self, text: str) -> list[str]:
        """Extract topic tags from text via simple heuristic analysis.

        Returns a deduplicated list of at most 5 tags.
        """
        tags: list[str] = []

        # People
        proper_nouns = _PROPER_NOUN_PATTERN.findall(text)
        novel_names = [n.lower() for n in proper_nouns if n not in _COMMON_CAPITALIZED]
        tags.extend(f"person:{n}" for n in set(novel_names))

        # Action items
        if any(p.search(text) for p in _ACTION_ITEM_PATTERNS):
            tags.append("action_item")

        # Decisions
        if any(p.search(text) for p in _DECISION_PATTERNS):
            tags.append("decision")

        # Dates
        if self._has_time_reference(text):
            tags.append("time_referenced")

        # Emotional
        if any(p.search(text) for p in _EMOTIONAL_PATTERNS):
            tags.append("emotional")

        # Explicit remember
        if any(p.search(text) for p in _REMEMBER_PATTERNS):
            tags.append("explicit_remember")

        # Deduplicate and cap
        seen: set[str] = set()
        unique_tags: list[str] = []
        for tag in tags:
            if tag not in seen:
                seen.add(tag)
                unique_tags.append(tag)
            if len(unique_tags) >= 5:
                break

        return unique_tags

    # ------------------------------------------------------------------
    # Session lifecycle
    # ------------------------------------------------------------------
    async def flush_session(self, session: Any) -> None:
        """Flush any buffered turns for a session that is ending.

        Should be called when a session closes so that un-summarised turns
        don't get lost.
        """
        session_id: str = session.session_id
        user_id: str = session.user_id

        buffered = self._turn_buffer.pop(session_id, [])
        self._turn_counter.pop(session_id, None)

        if buffered:
            logger.info(
                "Flushing %d buffered turns for session=%s",
                len(buffered),
                session_id,
            )
            try:
                await self._summarize_chunk(buffered, user_id)
            except Exception:
                logger.error("Failed to flush session buffer", exc_info=True)