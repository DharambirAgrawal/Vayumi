# =============================================================================
# server/agents/memory_agent.py — Memory Agent (Async Background)
# =============================================================================
#
# PURPOSE:
#   Reads and writes memory. Runs in the BACKGROUND after each response.
#   Never blocks the user-facing response. Responsible for:
#     - Deciding if a turn is "memorable" enough to store
#     - Summarizing conversation chunks every 10-20 turns
#     - Embedding and storing in ChromaDB (tagged with user_id)
#     - Updating SQLite for structured data (dates, people, tasks)
#     - Retrieving relevant memories for context building
#
# WHAT GETS SAVED:
#   - Conversations summarized every 10-20 turns into episodic chunks
#   - Explicit things user said to remember ("remember that...")
#   - Meeting notes (in meeting mode, everything is captured)
#   - Tasks and reminders with timestamps
#   - People mentioned with context
#
# WHAT DOES NOT GET SAVED:
#   - Every single turn verbatim (too much storage/tokens)
#   - Skill execution logs (discarded after success/failure noted)
#   - TTS audio (only text)
#
# MEMORY RECORD FORMAT (stored in ChromaDB):
#   {
#     "id": str,                    — Unique ID for the memory
#     "user_id": str,               — Owner of this memory
#     "speaker_id": str,            — Who was speaking
#     "content": str,               — Summarized content
#     "embedding_id": str,          — Reference to vector DB entry
#     "timestamp": datetime,
#     "sensitivity": str,           — "private" | "shared" | "public"
#     "tags": list[str]             — Topic tags for filtering
#   }
#
# SENSITIVITY RULES:
#   - "private": Only visible to account_owner persona
#   - "shared": Visible to account_owner and known_contacts
#   - "public": Visible to all personas (including guests)
#   Memory Agent tags every memory at write time based on content analysis.
#
# CLASS: MemoryAgent(BaseAgent)
#
#   __init__(self, llm_router, vector_store, sqlite_store, embedder):
#
#   async run(self, context: AgentContext) -> AgentResult:
#     Retrieval path — called by context_builder to get relevant memories.
#     Steps:
#       1. Embed context.input_text via embedder.embed()
#       2. Query vector_store with user_id filter, top_k=5
#       3. If input has time references → also query sqlite_store by date
#       4. Format results for injection
#       5. Return AgentResult with response_text = formatted memories
#
#   async process_turn(self, session, user_text: str, response) -> None:
#     Write path — called as background task after response is sent.
#     Steps:
#       1. Decide if turn is memorable (_is_memorable check)
#       2. If memorable: summarize the turn via LLM (fast model)
#       3. Determine sensitivity tag (_classify_sensitivity)
#       4. Embed summary via embedder.embed()
#       5. Store in vector_store with user_id metadata
#       6. If structured data detected (date, person, reminder) → store in sqlite_store
#       7. Increment turn counter; if >= threshold → summarize conversation chunk
#
#   def _is_memorable(self, text: str, response: str) -> bool:
#     Returns True if the turn contains: explicit "remember" request, names/people,
#     dates/times, action items, important decisions, or emotional significance.
#
#   def _classify_sensitivity(self, content: str) -> str:
#     Returns "private" | "shared" | "public" based on content analysis.
#     Default: "private" (safe default).
#
#   async _summarize_chunk(self, turns: list[dict], user_id: str):
#     Summarizes a batch of conversation turns into one episodic memory.
#     Uses fast LLM (llama-3.1-8b-instant) for summarization.
#
# PERSONA MEMORY ACCESS RULES (enforced at retrieval time):
#   PERSONA_MEMORY_ACCESS = {
#     "account_owner": "all",           — sees everything
#     "known_contact": "shared_only",   — sees shared + public only
#     "guest": "none",                  — no memory access
#   }
#
# IMPORTS NEEDED:
# =============================================================================

from server.agents.base_agent import BaseAgent, AgentContext, AgentResult
from server.llm.router import LLMRouter
from server.memory.vector_store import VectorStore
from server.memory.sqlite_store import SQLiteStore
from server.memory.embedder import Embedder

PERSONA_MEMORY_ACCESS = {
    "account_owner": "all",
    "known_contact": "shared_only",
    "guest": "none",
}

SUMMARIZE_EVERY_N_TURNS = 15


class MemoryAgent(BaseAgent):
    def __init__(self, llm_router: LLMRouter, vector_store: VectorStore,
                 sqlite_store: SQLiteStore, embedder: Embedder):
        self.llm_router = llm_router
        self.vector_store = vector_store
        self.sqlite_store = sqlite_store
        self.embedder = embedder
        self._turn_counter: dict[str, int] = {}

    async def run(self, context: AgentContext) -> AgentResult:
        pass

    async def process_turn(self, session, user_text: str, response) -> None:
        pass

    def _is_memorable(self, text: str, response: str) -> bool:
        pass

    def _classify_sensitivity(self, content: str) -> str:
        pass

    async def _summarize_chunk(self, turns: list[dict], user_id: str):
        pass
