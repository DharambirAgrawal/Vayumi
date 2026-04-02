# =============================================================================
# server/core/context_builder.py — Dynamic Context Assembly (User-Scoped)
# =============================================================================
#
# PURPOSE:
#   Assembles the full LLM input context for each turn. This is the engine
#   that makes Vayumi context-aware. It controls WHAT the LLM sees — the
#   permanent prompt, user identity, active persona, injected flags, relevant
#   memories, skill/MCP summaries, conversation window, and current input.
#
# CONTEXT ASSEMBLY ORDER (each turn):
#   [PERMANENT SYSTEM PROMPT]       — ~300 tokens, always present (from orchestrator)
#   [USER IDENTITY BLOCK]           — ~150 tokens, from authenticated user's profile
#   [ACTIVE PERSONA CONTEXT]        — ~200 tokens, depends on speaker in the room
#   [INJECTED FLAGS]                — 0-100 tokens, only if something happened (email, reminder)
#   [RELEVANT MEMORIES]             — 0-500 tokens, retrieved by vector search (user-scoped)
#   [SKILL REGISTRY SUMMARY]        — ~100 tokens, names + 1-line descriptions only
#   [MCP REGISTRY SUMMARY]          — ~50 tokens, user's enabled MCPs listed
#   [CONVERSATION WINDOW]           — last N turns, trimmed to fit budget
#   [CURRENT INPUT]                 — the user's message this turn
#
# TOKEN BUDGET SYSTEM:
#   Total budget varies by task complexity:
#     Simple conversation:     ~2500 tokens
#     With memory retrieval:   ~3000 tokens
#     Complex task (skill):    ~4000 tokens
#     Meeting mode:            ~3500 tokens (larger conversation window)
#
#   Priority when trimming to fit budget:
#     1. Drop oldest conversation turns first
#     2. Reduce retrieved memories from 5 to 3 to 1
#     3. NEVER trim: system prompt, user identity, current input
#
# CLASS: ContextBuilder
#
#   __init__(self, vector_store, sqlite_store, embedder, skill_registry, mcp_registry):
#     Stores references to all data sources needed for context assembly.
#
#   async build(self, session, text: str, speaker_id: str) -> dict:
#     The main context assembly function. Called by ws/handler.py process_user_turn.
#     Steps:
#       1. Load user profile from sqlite_store.get_user(session.user_id)
#       2. Build USER IDENTITY BLOCK from profile
#       3. Load active persona context:
#          - If speaker_id == session.user_id → load owner persona
#          - Else → lookup persona by speaker_id via persona mapping
#          - Apply context switch rules (hide private data for guests)
#       4. Get injected flags from session or flag store
#       5. Retrieve relevant memories:
#          - Embed user input via embedder.embed(text)
#          - Query vector_store with user_id filter, top_k=5
#          - If text has time references → also query sqlite_store by date
#       6. Get skill registry summary (names + descriptions only, ~100 tokens)
#       7. Get MCP registry summary (user's enabled MCPs, ~50 tokens)
#       8. Get conversation window from session.working_memory (last N turns)
#       9. Apply token budget trimming
#       10. Return assembled context dict with all blocks
#
#   def _estimate_tokens(self, text: str) -> int:
#     Rough token estimate: len(text) // 4
#
#   def _trim_to_budget(self, context: dict, budget: int) -> dict:
#     Applies priority-based trimming rules.
#
#   def _build_user_identity_block(self, user: UserAccount) -> str:
#     Formats user profile into a text block for LLM context.
#     Example: "User: Rahul | CS student | Goals: Build Vayumi, Learn AI agents
#              | Tone: casual and direct | Language: en"
#
#   def _build_persona_block(self, persona: dict) -> str:
#     Formats persona context into a text block.
#     Example: "Speaker: Rahul (account_owner) | Tone: casual and direct
#              | Context: CS student, building Vayumi, Uses Groq"
#
#   def _build_flags_block(self, flags: list[dict]) -> str:
#     Formats injected flags into text.
#     Example: "[FLAG] New email from Prof. Sharma: 'Project Deadline Update'"
#
#   def _build_memories_block(self, memories: list) -> str:
#     Formats retrieved memories into text.
#     Example: "- 2 days ago: Discussed Vayumi memory architecture"
#
# CONTEXT SWITCH RULES (from doc Section 5.4):
#   HIDE_FROM_NON_OWNER = [
#     "user_private_memories", "email_content", "calendar_details",
#     "financial_data", "reminders"
#   ]
#   TONE_MAP = {
#     "account_owner": "casual, personalized, full context",
#     "known_contact": "warm, context from relationship history",
#     "guest": "polite, neutral, minimal context",
#     "unknown": "friendly but cautious"
#   }
#
# IMPORTS NEEDED:
# =============================================================================

from server.memory.vector_store import VectorStore
from server.memory.sqlite_store import SQLiteStore
from server.memory.embedder import Embedder
from server.auth.models import UserAccount


HIDE_FROM_NON_OWNER = [
    "user_private_memories", "email_content", "calendar_details",
    "financial_data", "reminders"
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


class ContextBuilder:
    def __init__(self, vector_store: VectorStore, sqlite_store: SQLiteStore,
                 embedder: Embedder, skill_registry: dict, mcp_registry: dict):
        self.vector_store = vector_store
        self.sqlite_store = sqlite_store
        self.embedder = embedder
        self.skill_registry = skill_registry
        self.mcp_registry = mcp_registry

    async def build(self, session, text: str, speaker_id: str) -> dict:
        pass

    def _estimate_tokens(self, text: str) -> int:
        pass

    def _trim_to_budget(self, context: dict, budget: int) -> dict:
        pass

    def _build_user_identity_block(self, user: UserAccount) -> str:
        pass

    def _build_persona_block(self, persona: dict) -> str:
        pass

    def _build_flags_block(self, flags: list[dict]) -> str:
        pass

    def _build_memories_block(self, memories: list) -> str:
        pass
