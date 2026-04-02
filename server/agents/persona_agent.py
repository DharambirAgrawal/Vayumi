# =============================================================================
# server/agents/persona_agent.py — Persona Agent (Speaker Context Management)
# =============================================================================
#
# PURPOSE:
#   Manages speaker state and context switching. When the diarizer detects
#   a speaker change, the persona agent loads the appropriate persona context,
#   hides sensitive data from non-owners, and adjusts tone.
#   Also handles learning new contacts ("Meet Chris" flow).
#
# PERSONA CONTEXT FORMAT:
#   {
#     "persona_id": str,       — e.g. "rahul_self", "chris", "guest_unknown"
#     "user_id": str,          — Owner user (each user has their own personas)
#     "name": str,             — Display name
#     "role": str,             — "account_owner" | "known_contact" | "guest" | "unknown"
#     "tone": str,             — Tone directive for LLM
#     "known_facts": list[str],— Facts about this person
#     "active_topics": list[str], — Topics relevant to this person
#     "memory_access": str     — "full" | "shared_only" | "none"
#   }
#
# CONTEXT SWITCH FLOW (from doc Section 5.3):
#   1. Diarizer detects speaker_id
#   2. PersonaAgent maps speaker_id → persona_id:
#      a. Compare speaker voice embedding against user's known contacts
#      b. If match found → load that contact's persona
#      c. If no match → load "guest_unknown" persona
#      d. If speaker matches user's own voice → load owner persona
#   3. Apply context switch rules:
#      - Hide private data if speaker is not owner
#      - Adjust tone per role
#      - Set memory access level
#
# GUEST ARRIVAL/DEPARTURE THRESHOLDS:
#   GUEST_ARRIVAL_THRESHOLD_SECONDS = 2
#   GUEST_DEPARTURE_THRESHOLD_SECONDS = 30
#
# "MEET CHRIS" FLOW (from doc Section 10.2):
#   When owner says "Vayumi, this is Chris, he's my college friend":
#     1. Parse: introduction intent + name "Chris" + relationship "college friend"
#     2. Take Speaker_2's voice embedding from diarizer session_speakers
#     3. Save to contacts table:
#        INSERT INTO contacts (user_id, name, role, voice_embedding,
#          relationship_context, last_seen)
#     4. Create persona context for Chris:
#        {persona_id: "chris", role: "known_contact", tone: "friendly, warm",
#         known_facts: ["college friend"], memory_access: "shared_only"}
#     5. Reload context builder with new persona
#     6. Vayumi responds: "Nice to meet you, Chris!"
#
# CLASS: PersonaAgent(BaseAgent)
#
#   __init__(self, sqlite_store, diarizer):
#
#   async run(self, context: AgentContext) -> AgentResult:
#     Resolves speaker_id to persona context for the current turn.
#
#   async get_persona(self, user_id: str, speaker_id: str) -> dict:
#     Maps a speaker_id to its full persona context.
#     Steps:
#       1. If speaker_id matches user's own voice/id → return owner persona
#       2. Query contacts table for matching voice embedding (user-scoped)
#       3. If match found → build persona from contact data
#       4. If no match → return guest_unknown persona
#
#   async label_speaker(self, session, speaker_id: str, name: str | None):
#     Manual relabeling — called when user corrects speaker identity.
#     - Via voice: "Vayumi, that was Chris talking"
#     - Via client UI: {"type":"speaker_label","speaker_id":"speaker_2","name":"Rohan"}
#     Steps:
#       1. If name matches existing contact → re-map speaker_id to that contact
#       2. If new name → create new contact entry with speaker's voice embedding
#       3. Update session's active persona
#
#   async register_new_contact(self, user_id: str, name: str,
#                               voice_embedding: bytes, relationship: str) -> dict:
#     Creates a new contact and persona from an introduction.
#     Inserts into contacts table, returns the new persona context.
#
#   def _build_owner_persona(self, user: UserAccount) -> dict:
#     Builds the owner's persona from their user profile.
#
#   def _build_guest_persona(self, user_id: str) -> dict:
#     Returns the default guest_unknown persona.
#
# IMPORTS NEEDED:
# =============================================================================

from server.agents.base_agent import BaseAgent, AgentContext, AgentResult
from server.memory.sqlite_store import SQLiteStore
from server.voice.diarizer import SpeakerIdentifier
from server.auth.models import UserAccount

GUEST_ARRIVAL_THRESHOLD_SECONDS = 2
GUEST_DEPARTURE_THRESHOLD_SECONDS = 30


class PersonaAgent(BaseAgent):
    def __init__(self, sqlite_store: SQLiteStore, diarizer: SpeakerIdentifier):
        self.sqlite_store = sqlite_store
        self.diarizer = diarizer

    async def run(self, context: AgentContext) -> AgentResult:
        pass

    async def get_persona(self, user_id: str, speaker_id: str) -> dict:
        pass

    async def label_speaker(self, session, speaker_id: str, name: str | None):
        pass

    async def register_new_contact(self, user_id: str, name: str,
                                   voice_embedding: bytes, relationship: str) -> dict:
        pass

    def _build_owner_persona(self, user: UserAccount) -> dict:
        pass

    def _build_guest_persona(self, user_id: str) -> dict:
        pass
