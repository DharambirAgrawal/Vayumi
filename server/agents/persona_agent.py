# =============================================================================
# server/agents/persona_agent.py — Persona Agent (Speaker Context Management)
# =============================================================================

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from server.agents.base_agent import BaseAgent, AgentContext, AgentResult
from server.memory.sqlite_store import SQLiteStore
from server.voice.diarizer import SpeakerIdentifier
from server.auth.models import UserAccount

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Thresholds (from doc Section 5.3)
# ---------------------------------------------------------------------------
GUEST_ARRIVAL_THRESHOLD_SECONDS: int = 2
GUEST_DEPARTURE_THRESHOLD_SECONDS: int = 30

# Cosine-similarity threshold for voice-embedding matching.
# Above this value we consider two embeddings to represent the same speaker.
VOICE_MATCH_THRESHOLD: float = 0.82

# ---------------------------------------------------------------------------
# Tone presets per role
# ---------------------------------------------------------------------------
_TONE_DEFAULTS: dict[str, str] = {
    "account_owner": "natural, personal, proactive",
    "known_contact": "friendly, warm",
    "guest": "polite, neutral, privacy-conscious",
    "unknown": "polite, neutral, privacy-conscious",
}

# Memory-access levels per role
_MEMORY_ACCESS: dict[str, str] = {
    "account_owner": "full",
    "known_contact": "shared_only",
    "guest": "none",
    "unknown": "none",
}


# ---------------------------------------------------------------------------
# Small value-object that tracks per-session speaker timing
# ---------------------------------------------------------------------------
@dataclass
class _SpeakerPresence:
    """Tracks when a speaker was first / last heard in a session."""
    speaker_id: str
    persona_id: str | None = None
    first_seen: float = field(default_factory=time.time)
    last_seen: float = field(default_factory=time.time)
    announced: bool = False  # True once an arrival greeting has been issued


# ---------------------------------------------------------------------------
# Helper — cosine similarity between two embedding vectors
# ---------------------------------------------------------------------------
def _cosine_similarity(a: bytes | np.ndarray, b: bytes | np.ndarray) -> float:
    """Return cosine similarity ∈ [-1, 1] between two voice embeddings.

    Embeddings may arrive as raw ``bytes`` (float32 little-endian) or as
    pre-decoded ``np.ndarray``.  Both representations are supported so
    callers never have to worry about conversion.
    """
    if isinstance(a, (bytes, bytearray, memoryview)):
        a = np.frombuffer(a, dtype=np.float32)
    if isinstance(b, (bytes, bytearray, memoryview)):
        b = np.frombuffer(b, dtype=np.float32)

    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return float(np.dot(a, b) / (norm_a * norm_b))


# ===========================================================================
# PersonaAgent
# ===========================================================================
class PersonaAgent(BaseAgent):
    """Manages speaker personas and context switching.

    Responsibilities:
    * Map a diarizer ``speaker_id`` to a rich persona context dict.
    * Handle the "Meet Chris" introduction flow.
    * Allow manual relabelling of speakers (voice or UI).
    * Enforce memory-access / privacy rules per role.
    """

    # ---- construction ----

    def __init__(self, sqlite_store: SQLiteStore, diarizer: SpeakerIdentifier) -> None:
        self.sqlite_store = sqlite_store
        self.diarizer = diarizer

        # Per-session tracking: session_id → {speaker_id → _SpeakerPresence}
        self._session_presence: dict[str, dict[str, _SpeakerPresence]] = {}

        # In-memory cache: (user_id, speaker_id) → persona dict
        # Invalidated on label_speaker / register_new_contact.
        self._persona_cache: dict[tuple[str, str], dict[str, Any]] = {}

    # ------------------------------------------------------------------
    # BaseAgent entry-point
    # ------------------------------------------------------------------
    async def run(self, context: AgentContext) -> AgentResult:
        """Resolve the current speaker to a persona and attach it to the turn.

        ``context`` must carry at least:
        * ``context.user_id``   — the account owner
        * ``context.speaker_id`` — raw diarizer label for the current turn
        * ``context.session_id`` — the active session (for presence tracking)

        Returns an ``AgentResult`` whose ``data`` field contains the full
        persona context dict **and** a boolean ``context_switched`` flag.
        """
        user_id: str = context.user_id
        speaker_id: str = context.speaker_id
        session_id: str = context.session_id
        now = time.time()

        # 1. Resolve persona -------------------------------------------
        persona = await self.get_persona(user_id, speaker_id)

        # 2. Track presence & detect arrival/departure -----------------
        session_map = self._session_presence.setdefault(session_id, {})
        previous_persona_id: str | None = None

        if speaker_id in session_map:
            presence = session_map[speaker_id]
            presence.last_seen = now
            previous_persona_id = presence.persona_id
            presence.persona_id = persona["persona_id"]
        else:
            # Brand-new speaker in this session
            presence = _SpeakerPresence(
                speaker_id=speaker_id,
                persona_id=persona["persona_id"],
                first_seen=now,
                last_seen=now,
            )
            session_map[speaker_id] = presence

        # Determine whether a context switch actually happened
        context_switched = previous_persona_id is not None and previous_persona_id != persona["persona_id"]

        # Check guest arrival (speaker present ≥ threshold & not yet announced)
        guest_arrived = False
        if (
            persona["role"] in ("known_contact", "guest", "unknown")
            and not presence.announced
            and (now - presence.first_seen) >= GUEST_ARRIVAL_THRESHOLD_SECONDS
        ):
            guest_arrived = True
            presence.announced = True

        # Check guest departures — any previously-tracked non-owner speaker
        # whose last_seen exceeds the departure threshold
        departed_speakers: list[dict[str, Any]] = []
        for sid, sp in list(session_map.items()):
            if sid == speaker_id:
                continue
            if sp.persona_id and sp.persona_id not in ("owner", user_id):
                if (now - sp.last_seen) >= GUEST_DEPARTURE_THRESHOLD_SECONDS:
                    departed_speakers.append({"speaker_id": sid, "persona_id": sp.persona_id})
                    del session_map[sid]  # clean up

        # 3. Build result ---------------------------------------------
        result_data: dict[str, Any] = {
            "persona": persona,
            "context_switched": context_switched,
            "guest_arrived": guest_arrived,
            "departed_speakers": departed_speakers,
        }

        logger.info(
            "PersonaAgent resolved speaker=%s → persona=%s (switched=%s, arrived=%s)",
            speaker_id,
            persona["persona_id"],
            context_switched,
            guest_arrived,
        )

        return AgentResult(
            agent_name="persona_agent",
            success=True,
            data=result_data,
        )

    # ------------------------------------------------------------------
    # Core persona resolution
    # ------------------------------------------------------------------
    async def get_persona(self, user_id: str, speaker_id: str) -> dict[str, Any]:
        """Map a raw ``speaker_id`` to a full persona context dict.

        Resolution order:
        1. Check in-memory cache for a previous resolution.
        2. If ``speaker_id`` matches the owner's own voice → owner persona.
        3. Query the user's contacts table for a voice-embedding match.
        4. Fallback → guest_unknown persona.
        """
        cache_key = (user_id, speaker_id)
        if cache_key in self._persona_cache:
            return self._persona_cache[cache_key]

        # --- Step 1: Check if speaker is the account owner ---
        user = await self._fetch_user(user_id)
        if user is not None and self._is_owner_speaker(user, speaker_id):
            persona = self._build_owner_persona(user)
            self._persona_cache[cache_key] = persona
            return persona

        # --- Step 2: Voice-embedding lookup against contacts ---
        speaker_embedding = self._get_speaker_embedding(speaker_id)
        if speaker_embedding is not None:
            contacts = await self._fetch_contacts(user_id)
            best_match: dict[str, Any] | None = None
            best_score: float = -1.0

            for contact in contacts:
                contact_embedding = contact.get("voice_embedding")
                if contact_embedding is None:
                    continue
                score = _cosine_similarity(speaker_embedding, contact_embedding)
                if score > best_score:
                    best_score = score
                    best_match = contact

            if best_match is not None and best_score >= VOICE_MATCH_THRESHOLD:
                persona = self._build_contact_persona(user_id, best_match)
                self._persona_cache[cache_key] = persona
                logger.debug(
                    "Voice matched speaker=%s → contact=%s (score=%.3f)",
                    speaker_id,
                    best_match.get("name"),
                    best_score,
                )
                return persona

        # --- Step 3: Fallback → guest_unknown ---
        persona = self._build_guest_persona(user_id)
        # Do NOT cache unknown guests — embedding may improve with more audio
        return persona

    # ------------------------------------------------------------------
    # Manual relabelling
    # ------------------------------------------------------------------
    async def label_speaker(
        self,
        session: Any,
        speaker_id: str,
        name: str | None,
    ) -> dict[str, Any]:
        """Relabel a speaker manually (voice command or client UI).

        Parameters
        ----------
        session :
            The current session object; expected to expose at least
            ``session.user_id`` and ``session.session_id``.
        speaker_id :
            The diarizer label to relabel (e.g. ``"speaker_2"``).
        name :
            Human name to assign. ``None`` resets to unknown guest.

        Returns the (possibly new) persona context dict.
        """
        user_id: str = session.user_id
        session_id: str = session.session_id

        # Invalidate cache for this speaker
        self._persona_cache.pop((user_id, speaker_id), None)

        if name is None:
            # Reset to unknown guest
            persona = self._build_guest_persona(user_id)
            self._update_session_presence(session_id, speaker_id, persona["persona_id"])
            return persona

        # Check if name matches an existing contact
        contacts = await self._fetch_contacts(user_id)
        for contact in contacts:
            if contact.get("name", "").lower() == name.strip().lower():
                # Re-map speaker to existing contact & update its voice embedding
                speaker_embedding = self._get_speaker_embedding(speaker_id)
                if speaker_embedding is not None:
                    await self._update_contact_embedding(
                        contact_id=contact["id"],
                        voice_embedding=speaker_embedding,
                    )
                persona = self._build_contact_persona(user_id, contact)
                self._persona_cache[(user_id, speaker_id)] = persona
                self._update_session_presence(session_id, speaker_id, persona["persona_id"])
                logger.info("Relabelled speaker=%s → existing contact '%s'", speaker_id, name)
                return persona

        # New name — create a new contact
        speaker_embedding = self._get_speaker_embedding(speaker_id) or b""
        persona = await self.register_new_contact(
            user_id=user_id,
            name=name.strip(),
            voice_embedding=speaker_embedding,
            relationship="manually labelled",
        )
        self._persona_cache[(user_id, speaker_id)] = persona
        self._update_session_presence(session_id, speaker_id, persona["persona_id"])
        logger.info("Relabelled speaker=%s → new contact '%s'", speaker_id, name)
        return persona

    # ------------------------------------------------------------------
    # "Meet Chris" — register new contact
    # ------------------------------------------------------------------
    async def register_new_contact(
        self,
        user_id: str,
        name: str,
        voice_embedding: bytes,
        relationship: str,
    ) -> dict[str, Any]:
        """Create a brand-new contact and return its persona context.

        This is the backend for the "Meet Chris" introduction flow
        (doc Section 10.2).

        Steps:
        1. Generate a stable ``persona_id`` from the name.
        2. Insert into the ``contacts`` table.
        3. Build and return the persona context dict.
        """
        persona_id = self._name_to_persona_id(name)
        contact_id = str(uuid.uuid4())
        now_ts = time.time()

        contact_row: dict[str, Any] = {
            "id": contact_id,
            "user_id": user_id,
            "name": name,
            "persona_id": persona_id,
            "role": "known_contact",
            "voice_embedding": voice_embedding,
            "relationship_context": relationship,
            "last_seen": now_ts,
            "created_at": now_ts,
        }

        await self.sqlite_store.execute(
            """
            INSERT INTO contacts
                (id, user_id, name, persona_id, role, voice_embedding,
                 relationship_context, last_seen, created_at)
            VALUES
                (:id, :user_id, :name, :persona_id, :role, :voice_embedding,
                 :relationship_context, :last_seen, :created_at)
            """,
            contact_row,
        )

        # Invalidate any cached guest persona that may now match this contact
        keys_to_evict = [k for k in self._persona_cache if k[0] == user_id]
        for k in keys_to_evict:
            self._persona_cache.pop(k, None)

        persona = self._build_contact_persona(user_id, contact_row)
        logger.info(
            "Registered new contact '%s' (relationship='%s') for user=%s",
            name,
            relationship,
            user_id,
        )
        return persona

    # ------------------------------------------------------------------
    # Persona builders
    # ------------------------------------------------------------------
    def _build_owner_persona(self, user: UserAccount) -> dict[str, Any]:
        """Build the account owner's persona from their user profile."""
        user_id = getattr(user, "id", getattr(user, "user_id", "unknown"))
        display_name = getattr(user, "display_name", getattr(user, "name", "Owner"))

        # Pull any profile-level preferences if available
        preferences = getattr(user, "preferences", {}) or {}
        tone = preferences.get("tone", _TONE_DEFAULTS["account_owner"])

        return {
            "persona_id": f"{self._name_to_persona_id(display_name)}_self",
            "user_id": str(user_id),
            "name": display_name,
            "role": "account_owner",
            "tone": tone,
            "known_facts": [],
            "active_topics": [],
            "memory_access": _MEMORY_ACCESS["account_owner"],
        }

    def _build_contact_persona(self, user_id: str, contact: dict[str, Any]) -> dict[str, Any]:
        """Build a persona dict from a contacts-table row."""
        name = contact.get("name", "Unknown")
        relationship = contact.get("relationship_context", "")
        known_facts: list[str] = []
        if relationship:
            known_facts.append(relationship)

        return {
            "persona_id": contact.get("persona_id", self._name_to_persona_id(name)),
            "user_id": user_id,
            "name": name,
            "role": "known_contact",
            "tone": _TONE_DEFAULTS["known_contact"],
            "known_facts": known_facts,
            "active_topics": [],
            "memory_access": _MEMORY_ACCESS["known_contact"],
        }

    def _build_guest_persona(self, user_id: str) -> dict[str, Any]:
        """Return the default guest_unknown persona."""
        return {
            "persona_id": "guest_unknown",
            "user_id": user_id,
            "name": "Guest",
            "role": "unknown",
            "tone": _TONE_DEFAULTS["unknown"],
            "known_facts": [],
            "active_topics": [],
            "memory_access": _MEMORY_ACCESS["unknown"],
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _is_owner_speaker(self, user: UserAccount, speaker_id: str) -> bool:
        """Decide whether ``speaker_id`` corresponds to the account owner.

        Two strategies:
        1. The diarizer may tag the owner explicitly (e.g. ``speaker_id ==
           "owner"`` or matches the user's id).
        2. If the user object carries a stored ``voice_embedding``, compare
           it against the diarizer's embedding for ``speaker_id``.
        """
        user_id = str(getattr(user, "id", getattr(user, "user_id", "")))

        # Strategy 1: literal id match
        if speaker_id in ("owner", user_id, "speaker_0"):
            return True

        # Strategy 2: voice-embedding comparison
        owner_embedding = getattr(user, "voice_embedding", None)
        if owner_embedding is not None:
            speaker_embedding = self._get_speaker_embedding(speaker_id)
            if speaker_embedding is not None:
                score = _cosine_similarity(owner_embedding, speaker_embedding)
                if score >= VOICE_MATCH_THRESHOLD:
                    return True

        return False

    def _get_speaker_embedding(self, speaker_id: str) -> bytes | None:
        """Retrieve the current voice embedding for a diarizer speaker label.

        Delegates to the diarizer's session state. Returns ``None`` if the
        diarizer has no embedding yet (e.g. too little audio).
        """
        try:
            # The diarizer is expected to expose per-speaker embeddings.
            session_speakers: dict[str, Any] = getattr(self.diarizer, "session_speakers", {})
            speaker_data = session_speakers.get(speaker_id)
            if speaker_data is None:
                return None
            # speaker_data can be raw bytes or a dict with an "embedding" key
            if isinstance(speaker_data, (bytes, bytearray)):
                return bytes(speaker_data)
            if isinstance(speaker_data, dict):
                emb = speaker_data.get("embedding") or speaker_data.get("voice_embedding")
                if emb is not None:
                    if isinstance(emb, np.ndarray):
                        return emb.tobytes()
                    return bytes(emb)
            if isinstance(speaker_data, np.ndarray):
                return speaker_data.tobytes()
        except Exception:
            logger.debug("Could not retrieve embedding for speaker=%s", speaker_id, exc_info=True)
        return None

    async def _fetch_user(self, user_id: str) -> UserAccount | None:
        """Load a ``UserAccount`` from the store."""
        try:
            row = await self.sqlite_store.fetch_one(
                "SELECT * FROM users WHERE id = :user_id",
                {"user_id": user_id},
            )
            if row is None:
                return None
            # Construct a minimal UserAccount from the row
            if isinstance(row, dict):
                return UserAccount(**row)
            # row may be a sqlite3.Row — convert
            return UserAccount(**dict(row))
        except Exception:
            logger.debug("Could not fetch user=%s", user_id, exc_info=True)
            return None

    async def _fetch_contacts(self, user_id: str) -> list[dict[str, Any]]:
        """Return all contacts belonging to ``user_id``."""
        try:
            rows = await self.sqlite_store.fetch_all(
                "SELECT * FROM contacts WHERE user_id = :user_id",
                {"user_id": user_id},
            )
            if rows is None:
                return []
            return [dict(r) if not isinstance(r, dict) else r for r in rows]
        except Exception:
            logger.debug("Could not fetch contacts for user=%s", user_id, exc_info=True)
            return []

    async def _update_contact_embedding(
        self,
        contact_id: str,
        voice_embedding: bytes,
    ) -> None:
        """Update a contact's stored voice embedding."""
        try:
            await self.sqlite_store.execute(
                """
                UPDATE contacts
                SET voice_embedding = :voice_embedding,
                    last_seen = :last_seen
                WHERE id = :contact_id
                """,
                {
                    "contact_id": contact_id,
                    "voice_embedding": voice_embedding,
                    "last_seen": time.time(),
                },
            )
        except Exception:
            logger.warning("Failed to update embedding for contact=%s", contact_id, exc_info=True)

    def _update_session_presence(
        self,
        session_id: str,
        speaker_id: str,
        persona_id: str,
    ) -> None:
        """Update the presence tracker for a relabelled speaker."""
        session_map = self._session_presence.get(session_id)
        if session_map and speaker_id in session_map:
            session_map[speaker_id].persona_id = persona_id

    @staticmethod
    def _name_to_persona_id(name: str) -> str:
        """Derive a stable, filesystem-safe persona_id from a display name.

        >>> PersonaAgent._name_to_persona_id("Chris O'Brien")
        'chris_obrien'
        """
        cleaned = "".join(ch if ch.isalnum() or ch == " " else "" for ch in name)
        return cleaned.strip().lower().replace(" ", "_") or "unnamed"

    # ------------------------------------------------------------------
    # Session cleanup
    # ------------------------------------------------------------------
    def clear_session(self, session_id: str) -> None:
        """Remove all presence tracking state for a finished session."""
        self._session_presence.pop(session_id, None)
        # We keep the persona cache — it's keyed by (user_id, speaker_id)
        # and speaker_ids from different sessions don't collide.

    def clear_cache(self, user_id: str | None = None) -> None:
        """Invalidate the persona cache, optionally scoped to one user."""
        if user_id is None:
            self._persona_cache.clear()
        else:
            keys = [k for k in self._persona_cache if k[0] == user_id]
            for k in keys:
                del self._persona_cache[k]