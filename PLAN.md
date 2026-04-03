# Vayumi — Detailed Implementation Plan
### Every File, What It Does, What It Contains

**Version:** 1.3  
**Status:** Pre-implementation reference  

This document describes every file in the Vayumi project, what it is responsible for, what it contains, and how it connects to other files. Use this as a checklist and reference while building.

---

## Directory Overview

```
vayumi/
├── server/          ← All backend logic
│   ├── .env.example ← Template; copy to server/.env (secrets, not committed)
│   ├── main.py
│   ├── ws/          ← Unified WebSocket handler (single entry point)
│   ├── auth/        ← User accounts, login, JWT
│   ├── core/        ← Central brain: orchestrator, context, modes
│   ├── agents/      ← Specialized AI agents
│   ├── voice/       ← Audio pipeline: STT, TTS, diarization
│   ├── skills/      ← Pluggable skill system
│   ├── mcps/        ← Callable tool integrations
│   ├── memory/      ← Storage wrappers (SQLite, ChromaDB, embeddings)
│   ├── llm/         ← LLM routing and API clients
│   ├── config/      ← Server settings
│   ├── data/        ← Persistent data (SQLite DB, ChromaDB vector store)
│   └── models/      ← Downloaded ML weights (e.g. SpeechBrain speaker encoder cache)
├── client/          ← Frontend clients
│   ├── browser/     ← Web UI (.env.example = URL / config reference only)
│   └── esp32/       ← ESP32-S3-AUDIO-Board firmware (ESP-IDF + ESP-ADF)
├── requirements.txt
└── README.md
```

---

## server/paths.py

**Purpose:** Single source of truth for filesystem paths under the `server/` package. Resolves `server/data/` (SQLite, ChromaDB) and `server/models/` (downloaded weights) using `Path(__file__)`, so locations stay correct regardless of process working directory.

**Exports:** `SERVER_ROOT`, `DATA_DIR`, `MODELS_DIR`, `DEFAULT_SQLITE_DB`, `DEFAULT_VECTORDB_DIR`, `DEFAULT_KOKORO_ONNX`, `DEFAULT_KOKORO_VOICES`, `DEFAULT_SPEAKER_ENCODER_CACHE`.

---

## server/main.py

**Purpose:** Application entrypoint. Creates the FastAPI app, mounts routes, and starts background services.

**Contains:**
- FastAPI app instance
- WebSocket endpoint at `/ws/vayumi` — calls `websocket_endpoint()` from `ws/handler.py`
- REST route mounting (auth routes, API routes)
- Startup event: initializes SQLite (WAL mode), ChromaDB, loads registries
- Shutdown event: cleanup

**Key logic:**
- Does NOT contain WebSocket message handling directly — delegates to the unified handler
- Mounts the single `/ws/vayumi` route that calls `websocket_endpoint()`

**Depends on:** `auth/`, `ws/handler.py`, `memory/`

---

## server/ws/handler.py

**Purpose:** Unified WebSocket handler. **Single entry point** for all real-time client communication. Auth, message dispatch, response streaming, and cleanup all live here.

**Contains:**
- `websocket_endpoint(websocket)` — the single entry function called by FastAPI
- `authenticate_connection(websocket)` — validates first auth message (canonical), returns Session or None
- `message_loop(session, websocket)` — receives messages, dispatches via `MESSAGE_HANDLERS` dict
- `MESSAGE_HANDLERS` — dict mapping message types to handler functions:
  - `wake` → `handle_wake` (transition SLEEP → ACTIVE, start active window timer)
  - `audio_chunk` → `handle_audio_chunk` (ignore if SLEEP; echo-aware VAD → STT → diarize → process_user_turn)
  - `text_input` → `handle_text_input` (direct text → process_user_turn, resets active timer)
  - `interrupt` → `handle_interrupt` (stop current response, set playback_state=IDLE)
  - `playback_done` → `handle_playback_done` (set playback_state=IDLE, transition to ACTIVE, reset timer)
  - `mode_switch` → `handle_mode_switch` (switch mode, notify client)
  - `speaker_label` → `handle_speaker_label` (label a speaker)
- `process_user_turn(session, text, speaker_id, source)` — **shared processing path** for both voice and text input. Builds context, calls orchestrator, streams response (sets `playback_state=PLAYING`), fires background memory write. Calls `_drain_input_queue` after completion.
- `_drain_input_queue(session)` — after a task completes, drains the input queue: if any queued item is a cancel intent ("never mind", "cancel", etc.) → discards entire queue; otherwise processes only the **last** queued item (most recent intent wins).
- `CANCEL_WORDS` — set of cancel phrases checked during queue drain.
- Identity mapping contract:
  - `user_id`: authenticated account owner (data isolation scope)
  - `speaker_id`: current utterance speaker track (`speaker_2`, `rahul`, etc.)
  - `persona_id`: policy/tone/access identity derived from `speaker_id`
- `stream_response(session, response)` — streams text + TTS audio to client sentence by sentence. Uses **1-sentence TTS lookahead** (pre-synthesizes sentence N+1 while sentence N is being sent to avoid speech gaps). Does NOT own state — caller sets `activation_state`/`playback_state` before calling. Client sends `playback_done` when audio finishes.
- `cleanup_session(session)` — called on disconnect (guaranteed via try/finally). Cancels active window timer.

**Key design:**
- One file, one entry point — easy to debug
- Adding a new message type = one async function + one dict entry
- Voice and text input converge at `process_user_turn` — zero duplication
- All responses flow through `stream_response` — consistent behavior for acks, results, conversations
- Canonical auth path is first WS message `{"type":"auth","token":"..."}`; query-param token is optional legacy compatibility only
- Echo-aware: `handle_audio_chunk` checks `activation_state` (ignores in SLEEP) and `playback_state` (routes to interrupt handler during SPEAKING)
- Active window management: timer resets on user turn, playback_done, and text input; fires `sleep` event on 30s silence; disabled during meeting mode
- Session starts in `SLEEP` / `IDLE` state; `wake` message transitions to `ACTIVE`

**Depends on:** `auth/jwt_handler.py`, `core/orchestrator.py`, `core/context_builder.py`, `core/interrupt_handler.py`, `core/mode_manager.py`, `voice/vad.py`, `voice/stt.py`, `voice/diarizer.py`, `voice/tts.py`, `agents/memory_agent.py`, `agents/persona_agent.py`

---

### Identity Contract (Cross-Module)

| Field | Meaning | Produced by | Consumed by |
|---|---|---|---|
| `user_id` | Authenticated account owner | Auth/JWT | Storage, rate limits, isolation |
| `speaker_id` | Current utterance speaker track | Diarizer (voice) or default `user_id` (text) | Persona Agent, context builder |
| `persona_id` | Persona policy identity for response/access | Persona Agent | Context builder, orchestrator |

Rules:
- Data access isolation always uses `user_id`.
- Tone/access policy uses `persona_id`.
- If mapping confidence is low, `persona_id = guest_unknown` (safe default).

### Session Object (canonical field list)

Every WebSocket connection creates one `Session`. This is the most-used object in the system.

| Field | Type | Purpose |
|---|---|---|
| `session_id` | `str` | Unique session identifier |
| `user_id` | `str` | Authenticated account owner (from JWT) |
| `websocket` | `WebSocket` | The active connection |
| `client_type` | `str` | `"browser"` / `"esp32"` / `"mobile"` |
| `active_speaker` | `str` | Current speaker's `persona_id` |
| `mode` | `str` | `"normal"` / `"meeting"` / `"focus"` |
| `working_memory` | `list` | Current conversation turns |
| `task_state` | `dict` | `{"status": "idle"}` or `{"status": "running", ...}` |
| `input_queue` | `list` | User inputs received while a task is running |
| `activation_state` | `str` | `"SLEEP"` / `"ACTIVE"` / `"SPEAKING"` / `"INTERRUPTED"` |
| `playback_state` | `str` | `"IDLE"` / `"PLAYING"` (controls echo gating) |
| `_active_window_handle` | `asyncio.TimerHandle` | 30s active window cancel handle |
| `connected_at` | `datetime` | Connection timestamp |

Methods: `send(data)`, `reset_active_window_timer()`, `_on_active_timeout()`.

New sessions start with `activation_state="SLEEP"`, `playback_state="IDLE"`, `task_state={"status":"idle"}`, `input_queue=[]`.

---

## server/auth/router.py

**Purpose:** HTTP endpoints for user registration and login.

**Contains:**
- `POST /api/auth/register` — creates new user account (email, password, display name)
- `POST /api/auth/login` — validates credentials, returns JWT token
- `GET /api/users/me` — returns authenticated user's profile

**Key logic:**
- Password hashing with bcrypt on registration
- JWT token generation on successful login
- Token includes `user_id` and expiration

**Depends on:** `auth/jwt_handler.py`, `auth/models.py`, `memory/sqlite_store.py`

---

## server/auth/jwt_handler.py

**Purpose:** Creates and validates JWT tokens.

**Contains:**
- `create_token(user_id)` — generates a signed JWT with expiry
- `validate_token(token)` — verifies signature, checks expiry, returns `user_id` or `None`
- JWT secret key (loaded from environment variable `JWT_SECRET`)

**Key logic:**
- Tokens expire after configurable period (default: 24 hours)
- Used by both REST endpoints and WebSocket auth

**Depends on:** PyJWT library

---

## server/auth/models.py

**Purpose:** Data model for user accounts.

**Contains:**
- `UserAccount` dataclass/pydantic model with fields:
  - `user_id`, `display_name`, `email`, `password_hash`
  - `voice_embedding`, `embedding_model_version`
  - `profile` (JSON: occupation, goals, tone, language)
  - `enabled_mcps` (JSON array)
  - `created_at`

**Depends on:** nothing (pure data model)

---

## server/core/orchestrator.py

**Purpose:** The Central Consciousness. Decides what to do with each turn, coordinates agents, assembles responses.

**Contains:**
- `Orchestrator` class with `run(session, context, input_text)` method
- Intent detection logic: is this a simple reply? Skill-needed? MCP call? Multi-step?
- Agent coordination: runs Task Agent if needed, fires Memory Agent in background
- Response assembly: combines agent results into final text
- Long-running task detection: if task will take time, returns instant acknowledgment first

**Key logic:**
1. Receives `context` from `process_user_turn` (built by `context_builder.build(session, text, speaker_id)`)
2. Makes LLM call via `llm/router.py` with assembled context
3. If task will take time → generates instant ack ("Sure, let me check that"), returns structured `{"ack": str, "result": str}` dict; `ws/handler.py` streams both via `stream_response`
4. If LLM response includes tool call → dispatch to skill_runner or MCP
5. If multi-step → loop with Task Agent
6. Returns response to handler: `str`, `AsyncIterator[str]`, or `{"ack": str, "result": str}` dict
7. Deferred tasks ("tell me later") → runs task, stores result as deferred artifact metadata in episodic memory instead of responding immediately
8. Memory Agent is fired by `process_user_turn` (not orchestrator) — `asyncio.create_task(memory_agent.process_turn(...))`

**Depends on:** `core/context_builder.py`, `core/mode_manager.py`, `agents/*`, `llm/router.py`, `skills/skill_runner.py`, `mcps/`

---

## server/core/context_builder.py

**Purpose:** Assembles the LLM context window for each turn. This is the brain's "working desk" — it decides what information the LLM sees.

**Contains:**
- `ContextBuilder` class
- `build(session, input_text, speaker_id)` method that returns the full prompt array
- Token budget management: counts tokens, trims to fit
- Priority rules for trimming (oldest conversation first, then memories)

**Key logic:**
1. Load permanent system prompt (~300 tokens)
2. Load user profile from session's `user_id` (~150 tokens)
3. Load active persona context based on `speaker_id` (~200 tokens)
4. Load injected flags if any (0-100 tokens)
5. Query relevant memories via `memory/vector_store.py` (0-500 tokens, filtered by user_id)
6. Load skill registry summary (~100 tokens)
7. Load MCP registry summary (~50 tokens, filtered by user's enabled MCPs)
8. Append conversation window from session working memory
9. Append current input
10. Trim if over budget

**Depends on:** `memory/vector_store.py`, `memory/sqlite_store.py`, `skills/skill_registry.json`, `mcps/mcp_registry.json`

---

## server/core/mode_manager.py

**Purpose:** Handles mode switching (normal, meeting, focus) per session.

**Contains:**
- `ModeManager` class
- `NormalMode`, `MeetingMode`, `FocusMode` classes with `on_enter()` and `on_exit()` hooks
- `switch(session, mode_name, trigger)` method

**Key logic:**
- Meeting mode: increases diarizer sensitivity, starts transcript logging, suppresses casual responses
- Focus mode: filters non-critical flags, responds only to direct questions
- Normal mode: default behavior
- Mode state is stored on the Session object (per-user, per-connection)

**Depends on:** nothing directly (called by `ws/handler.py` `handle_mode_switch` and by orchestrator for mode-aware behavior)

---

## server/core/interrupt_handler.py

**Purpose:** Detects and handles interruptions — when the user speaks while Vayumi is speaking. Echo-aware: only triggers on real user speech, not Vayumi's own voice.

**Contains:**
- `InterruptHandler` class
- `handle(session, interrupt_event)` method — handles typed interrupt events (from client button or classified speech)
- `handle_speech_interrupt(session, audio_bytes)` — called by `handle_audio_chunk` when VAD detects speech during SPEAKING state. Transcribes the speech, classifies as stop/redirect/add_context.
- `stop_current_response(session)` — stops TTS, cancels task, resets playback/activation state
- Three interrupt types: `stop`, `redirect`, `add_context`

**Key logic:**
- `stop`: cancels TTS playback and current task, `activation_state → ACTIVE`, `playback_state → IDLE`
- `redirect`: cancels current response, routes new input to orchestrator, resets states
- `add_context`: pauses TTS, appends new info to current task context, `activation_state → INTERRUPTED`
- Interrupt position tracking (which sentence was Vayumi on when interrupted)
- All interrupt paths reset `session.playback_state = "IDLE"` and call `session.reset_active_window_timer()`
- Two interrupt entry paths:
  1. Client sends `{"type":"interrupt"}` (button press or ESP32 wake word during speech) → `handle_interrupt` in handler
  2. Echo-cancelled speech detected by VAD during SPEAKING state → `handle_speech_interrupt` classifies intent

**Depends on:** `voice/tts.py` (to stop/pause audio), `voice/stt.py` (to transcribe interrupt speech)

---

## server/agents/base_agent.py

**Purpose:** Base interface that all agents implement.

**Contains:**
- `BaseAgent` abstract class with:
  - `async run(context: AgentContext) -> AgentResult`
  - `async run_background(context: AgentContext) -> None`
- `AgentContext` dataclass: `user_id`, `input_text`, `speaker_id`, `mode`, `working_memory`, `injected_flags`, `skill_registry`, `mcp_registry`
- `AgentResult` dataclass: `response_text`, `memories_to_write`, `skills_executed`, `flags_consumed`, `follow_up_tasks`

**Depends on:** nothing (pure interface)

---

## server/agents/memory_agent.py

**Purpose:** Writes memories in background after each response. Memory *reading* is done by context_builder via vector_store directly.

**Contains:**
- `MemoryAgent` class (extends BaseAgent)
- `process_turn(session, text, response)`: canonical method called by `process_user_turn` via `asyncio.create_task`. Decides if current turn is memorable, summarizes, embeds, stores. (Internally calls `run_background` from BaseAgent interface.)

**Key logic:**
- Summarizes conversation chunks every 10-20 turns
- Embeds summaries via `memory/embedder.py`
- Stores in ChromaDB via `memory/vector_store.py` (tagged with `user_id`)
- Stores structured data (reminders, people, dates) in SQLite via `memory/sqlite_store.py`
- Tags memories with sensitivity: `private`, `shared`, `public`

**Depends on:** `memory/vector_store.py`, `memory/sqlite_store.py`, `memory/embedder.py`, `llm/router.py` (for summarization LLM call)

---

## server/agents/task_agent.py

**Purpose:** Handles multi-step task execution. Called when a task needs skill execution or multiple passes.

**Contains:**
- `TaskAgent` class (extends BaseAgent)
- `run()`: reads skill doc, creates execution plan, executes steps, returns result

**Key logic:**
- Loads the skill SKILL.md into context
- Plans steps: [extract, process, summarize, format]
- Executes each step (may involve LLM calls or skill runner calls)
- Returns structured result to orchestrator

**Depends on:** `skills/skill_runner.py`, `llm/router.py`

---

## server/agents/search_agent.py

**Purpose:** Handles web search tasks. Decides if search is needed, builds queries, summarizes results.

**Contains:**
- `SearchAgent` class (extends BaseAgent)
- `run()`: takes search intent, calls web_search MCP, processes results, returns summary

**Key logic:**
- Builds effective search queries from user intent
- Calls `mcps/web_search.py`
- Summarizes results with LLM
- Returns formatted answer

**Depends on:** `mcps/web_search.py`, `llm/router.py`

---

## server/agents/persona_agent.py

**Purpose:** Manages speaker state and context switching when different people are detected in the room. Also handles learning new people from introductions.

**Contains:**
- `PersonaAgent` class (extends BaseAgent)
- `run()`: triggered on speaker change, loads appropriate persona context
- `label_speaker(session, speaker_id, name)`: called when owner introduces someone or corrects a misidentification
- `_create_persona_from_introduction(session, speaker_id, name, relationship)`: builds a new persona from conversational introduction

**Key logic:**
- Looks up speaker_id in authenticated user's contacts (via SQLite, filtered by `user_id`)
- If known: loads their persona profile (tone, known_facts, memory_access)
- If unknown: creates temporary guest persona
- Hides private data when non-owner is speaking
- Tracks guest arrival/departure using silence thresholds
- **Learning new people:** When owner says "this is Chris, my college friend":
  1. Orchestrator detects introduction intent, calls persona_agent
  2. Takes Speaker_2's voice embedding from diarizer's session_speakers
  3. Saves to contacts table (name, voice_embedding, relationship_context)
  4. Creates persona context (role: known_contact, memory_access: shared_only)
  5. Future sessions: diarizer matches Chris's voice automatically → persona loaded
- **Manual correction via label_speaker():** Reassigns a speaker_id to a name (called from `handle_speaker_label` in ws/handler.py or from voice command "that was Chris")

**Depends on:** `memory/sqlite_store.py` (contacts table), `core/context_builder.py`, `voice/diarizer.py` (for voice embedding access)

---

## server/voice/stt.py

**Purpose:** Speech-to-text wrapper around Groq Whisper API.

**Contains:**
- `STTEngine` class
- `transcribe(audio_bytes)` method → returns text string
- Error handling: retries on timeout, returns error message on failure

**Key logic:**
- Sends audio to Groq Whisper API
- Returns transcription text
- Fast (~200ms for short utterances)

**Depends on:** Groq SDK, `GROQ_API_KEY`

---

## server/voice/tts.py

**Purpose:** Text-to-speech using Kokoro-ONNX. Runs locally, no API needed.

**Contains:**
- `TTSEngine` class
- `synthesize_stream(text_generator)` — accepts streaming text, yields audio chunks per sentence
- `stop()` — cancels current synthesis
- `pause()` / `resume()` — for interrupt handling

**Key logic:**
- Buffers incoming tokens until sentence boundary
- Synthesizes each complete sentence into audio
- Yields audio chunks for immediate playback
- Sentence boundary detection: `.`, `!`, `?`, or long pause markers

**Depends on:** kokoro-onnx library; model files in `server/models/`: `kokoro-v0_19.onnx`, `voices.bin` (see `server.paths.DEFAULT_KOKORO_*`).

---

## server/voice/diarizer.py

**Purpose:** Identifies who is speaking based on voice embeddings.

**Embedding model:** SpeechBrain ECAPA-TDNN (`spkrec-ecapa-voxceleb`)
- 192-dim embedding vector per audio segment
- ~200-400ms per inference on CPU (runs via `asyncio.to_thread` to avoid blocking)
- ~400MB model download (cached after first run)
- Loaded once at server startup, shared across sessions

**Contains:**
- `SpeakerIdentifier` class
- `__init__()` — loads `EncoderClassifier.from_hparams(source="speechbrain/spkrec-ecapa-voxceleb")`
- `identify(audio_segment, user_id)` — async, returns speaker_id. Embedding extraction via `asyncio.to_thread`
- `_embed(audio_segment)` — blocking call that converts audio to tensor and runs `encoder.encode_batch`
- `register_speaker(user_id, name, audio_sample)` — async, enrolls a new voice
- `reassign_speaker(session, speaker_id, name)` — manual correction of misidentified speaker

**Key logic:**
- Extracts voice embedding from audio segment using ECAPA-TDNN
- Compares against known speakers (loaded from user's contacts table, scoped by `user_id`)
- If cosine similarity > threshold: returns known speaker ID (e.g., "chris")
- If similarity between thresholds: uncertain — defaults to guest (safe fallback, no private data exposed)
- If no match: assigns temporary speaker ID (speaker_1, speaker_2, etc.)
- Registered speakers persist across sessions (stored in contacts table with voice_embedding)
- Primary job: distinguish "owner" vs "not owner" — this is the most reliable and most important distinction

**Accuracy notes (with ECAPA-TDNN):**
- Owner vs one other person: ~90%+ (most common scenario)
- Owner vs enrolled contact: ~85% (depends on enrollment audio quality)
- 2 unknown guests: ~70-80% within a session
- 3+ simultaneous/overlapping speakers: best-effort only
- Different conditions (whispering, phone, noise) degrade accuracy

**Depends on:** `memory/sqlite_store.py` (contacts table with voice_embedding), `speechbrain`, `torch`

---

### Meeting-Mode Acceptance Criteria (Phase 1)

- If diarizer confidence is low, speaker is treated as `guest_unknown` (never owner-escalated).
- Mixed-speaker meeting must not expose owner-private memory on guest turns.
- `speaker_label` correction must relabel transcript/persona mapping within the same session.
- Owner introduction ("this is Chris") must create/update contact enrollment for future sessions.
- Meeting summary remains useful even when attribution confidence is imperfect.

---

## server/voice/vad.py

**Purpose:** Voice Activity Detection — determines when someone is speaking vs silence. Includes echo-aware gating to prevent Vayumi's own voice from triggering false detections.

**Contains:**
- `VADEngine` class
- `process(audio_chunk, session)` — returns `VADResult(has_speech)`. Echo-aware: checks `session.playback_state` before deciding.
- Configurable thresholds: `normal_threshold` (for IDLE playback), `echo_threshold` (raised, for PLAYING playback)
- `compute_energy(chunk)` — calculates audio energy for threshold comparison
- `_sustained_speech(chunk)` — checks if detected speech exceeds minimum duration (~300ms)

**Key logic:**
- Filters out background noise
- Detects speech onset and offset
- **Echo gating:** When `session.playback_state == "PLAYING"`:
  - Requires higher energy threshold (above echo residue level)
  - Requires sustained duration (>300ms) — short echo bursts are ignored
  - Only loud, sustained human speech passes through
- When `session.playback_state == "IDLE"`: normal sensitivity
- ESP32 sends echo-cancelled audio (hardware AEC), so gating is a safety net
- Browser audio has no hardware AEC, so gating is the primary defense
- Used to: only send speech to STT (save API calls), detect interrupts, detect guest departure

**Depends on:** webrtcvad or silero-vad library

---

## server/skills/skill_runner.py

**Purpose:** Loads skill documentation and executes skills.

**Contains:**
- `SkillRunner` class
- `load_skill_doc(skill_id)` — reads and returns SKILL.md content
- `execute(skill_id, input_data)` — runs the skill's run.py with input, returns output
- `SkillRegistry` class — loads and queries skill_registry.json

**Key logic:**
- Registry is loaded once at startup, provides `lookup(keywords)` to match user intent to skill
- Skill doc is injected into context only when executing that skill
- Execution: writes input.json, runs run.py, reads output.json
- Timeout: 30 seconds max per skill execution

**Depends on:** `skills/skill_registry.json`, individual skill directories

---

## server/skills/skill_registry.json

**Purpose:** Lightweight index of all available skills. Always loaded in context (~100 tokens).

**Contains:** Array of skill entries, each with:
- `id`: unique skill identifier
- `name`: human-readable name
- `description`: one-line description (what the LLM sees)
- `trigger_keywords`: words that suggest this skill is needed
- `doc_path`: path to the full SKILL.md

---

## server/skills/web_reader/ (example skill)

### SKILL.md
- Description of what web_reader does
- Input format: `{"url": "...", "question": "..."}`
- Output format: `{"success": true, "result": "...", "metadata": {...}}`
- Requirements: requests, beautifulsoup4
- Usage example

### run.py
- Reads input.json
- Fetches the URL
- Extracts text content
- Writes output.json with extracted text

---

## server/mcps/mcp_registry.json

**Purpose:** Registry of all available MCP tools. Split into always-on and on-demand.

**Contains:**
- `always_on`: tools always listed in context (web_search, set_reminder, get_datetime, get_reminders)
- `on_demand`: tools available only when user enables them (gmail, google_calendar, smart_home)

Each entry has: `name`, `description`, `when_to_use` (for always-on), `requires_auth` (for on-demand)

---

## server/mcps/web_search.py

**Purpose:** Web search MCP. Searches the web and returns results.

**Contains:**
- `web_search(query)` function
- Returns structured results: list of `{title, url, snippet}`

**Key logic:**
- Calls a search API (DuckDuckGo, SerpAPI, or similar)
- Returns top 5 results with snippets
- SearchAgent then summarizes these with LLM

**Depends on:** search API library

---

## server/mcps/reminders.py

**Purpose:** Reminder MCP. Create, list, and manage reminders.

**Contains:**
- `set_reminder(user_id, text, due_datetime)` — creates reminder in SQLite
- `get_reminders(user_id, date)` — returns reminders for a date
- `complete_reminder(user_id, reminder_id)` — marks as done

**Key logic:**
- All queries scoped by `user_id`
- Background check: on each turn, check if any reminder is due and inject flag

**Depends on:** `memory/sqlite_store.py`

---

## server/memory/vector_store.py

**Purpose:** Wrapper around ChromaDB for semantic memory search.

**Contains:**
- `VectorStore` class
- `store(user_id, content, metadata)` — embeds and stores a memory
- `query(user_id, query_text, top_k)` — semantic search, filtered by user_id
- `delete(user_id, memory_id)` — removes a memory

**Key logic:**
- Every store and query operation includes `user_id` in metadata/filter
- Uses `memory/embedder.py` for embedding generation
- ChromaDB collection: `episodic_memory` with cosine similarity
- Deferred artifacts (`artifact_type="deferred_read"`) store metadata: `source_url`, `created_at`, `sensitivity`
- Deferred retrieval path filters by `user_id + artifact_type`, then semantic rank, then recency rank

**Depends on:** chromadb library, `memory/embedder.py`

---

## server/memory/sqlite_store.py

**Purpose:** Wrapper around SQLite for structured data (users, reminders, meetings, contacts, memory episodes, flags).

**Contains:**
- `SQLiteStore` class
- CRUD methods for each table: `create_user()`, `get_user()`, `create_reminder()`, `get_reminders()`, etc.
- All methods require `user_id` parameter for data isolation
- Connection initialization with WAL mode

**Key logic:**
- `__init__`: connects to `server.paths.DEFAULT_SQLITE_DB` (i.e. `server/data/vayumi.db`), enables WAL mode, creates tables if not exist
- Every query includes `WHERE user_id = ?` (except user lookup by email for login)
- Returns typed objects (not raw tuples)

**Depends on:** sqlite3 stdlib

---

## server/memory/embedder.py

**Purpose:** Generates text embeddings using sentence-transformers.

**Contains:**
- `Embedder` class
- `embed(text)` → returns list of floats (384-dim vector)
- Model loaded once at startup, reused for all embedding calls

**Key logic:**
- Uses `all-MiniLM-L6-v2` model (local, free)
- Called by vector_store for both storing and querying
- Called async (never blocks response)

**Depends on:** sentence-transformers library

---

## server/llm/router.py

**Purpose:** Routes LLM requests to the right provider (Groq or Gemini) based on task type and rate limits.

**Contains:**
- `LLMRouter` class
- `route(user_id, task_type, estimated_tokens)` → returns (provider, model) or rate limit error
- `stream(provider, model, prompt)` → async generator of tokens
- Per-user rate limiter
- Global rate limit tracking for Groq API

**Key logic:**
- Fast tasks (orchestrate, memory, search) → small Groq model
- Complex tasks (task agent, reasoning) → large Groq model
- If Groq rate limited → fallback to Gemini
- Per-user fairness: each user gets max N requests per minute

**Depends on:** `llm/groq_client.py`, `llm/gemini_client.py`

---

## server/llm/groq_client.py

**Purpose:** Wrapper around Groq API for LLM calls.

**Contains:**
- `GroqClient` class
- `stream_chat(model, messages)` → async generator of tokens
- Error handling: timeout, rate limit, API errors

**Depends on:** groq SDK, `GROQ_API_KEY`

---

## server/llm/gemini_client.py

**Purpose:** Wrapper around Google Gemini API for fallback LLM calls.

**Contains:**
- `GeminiClient` class
- `stream_chat(model, messages)` → async generator of tokens
- Error handling: timeout, API errors

**Depends on:** google-generativeai SDK, `GEMINI_API_KEY`

---

## server/config/settings.json

**Purpose:** Server-level configuration (not per-user).

**Contains:**
```json
{
  "server": {
    "host": "0.0.0.0",
    "port": 8000
  },
  "database": {
    "sqlite_path": "data/vayumi.db",
    "vectordb_path": "data/vectordb"
  },
  "voice": {
    "tts_model_path": "models/kokoro-v0_19.onnx",
    "tts_voices_path": "models/voices.bin",
    "vad_sensitivity": 2
  },
  "llm": {
    "groq_rpm_limit": 30,
    "per_user_rpm_limit": 10,
    "per_user_tpm_limit": 50000,
    "default_max_tokens": 1000
  },
  "context": {
    "simple_turn_budget": 2500,
    "complex_turn_budget": 4000,
    "max_conversation_turns": 20,
    "max_retrieved_memories": 5
  },
  "session": {
    "reconnect_window_seconds": 60,
    "jwt_expiry_hours": 24
  }
}
```

---

## client/browser/index.html

**Purpose:** Main HTML page for the browser client.

**Contains:**
- Login form (email + password)
- Main UI after login: status indicator, transcript area, mode toggle button
- Audio elements for playback
- Includes app.js and ui.js

---

## client/browser/app.js

**Purpose:** Core client logic — authentication, WebSocket connection, audio streaming.

**Contains:**
- Login flow: POST to /api/auth/login, store JWT token
- WebSocket connection to `/ws/vayumi`
- First message (canonical): `{"type": "auth", "token": "..."}`
- Optional legacy compatibility: token in query param (if enabled server-side)
- MediaRecorder setup: captures mic audio, sends as audio_chunk events
- Audio playback: receives audio_chunk events, plays via AudioContext
- Event sending: interrupt, mode_switch, speaker_label
- Reconnection logic on disconnect

---

## client/browser/ui.js

**Purpose:** UI updates — status display, transcript rendering, mode indicator.

**Contains:**
- Status indicator updates (listening / processing / speaking / idle)
- Transcript display: shows user speech and Vayumi responses
- Mode indicator: shows current mode (normal / meeting / focus)
- Flag notifications: shows toast-style alerts for email, reminder, etc.

---

## client/esp32/ (ESP32-S3-AUDIO-Board Firmware)

**Board:** ESP32-S3-AUDIO-Board (ESP32-S3R8, 16MB Flash, 8MB PSRAM, ES7210 mic ADC, ES8311 speaker DAC, 7x RGB LED ring, PCF85063 RTC)

**Framework:** ESP-IDF + ESP-ADF (C). Required for access to AEC/NS/BSS audio front-end pipeline and ESP-SR wake word detection. MicroPython/Arduino cannot access these features.

### client/esp32/main/main.c

**Purpose:** Application entrypoint. WiFi init, task orchestration, component initialization.

**Contains:**
- WiFi STA setup (credentials from NVS)
- Component initialization order: audio pipeline → wake word → WebSocket → LED
- FreeRTOS task creation for audio streaming and wake word detection
- Reconnection logic with exponential backoff on WiFi/WS disconnect

### client/esp32/main/audio_pipeline.c

**Purpose:** ESP-ADF audio front-end pipeline. Handles echo cancellation, noise suppression, and audio I/O.

**Contains:**
- I2S configuration for ES7210 (mic input) and ES8311 (speaker output)
- AEC (Acoustic Echo Cancellation): feeds speaker output as reference signal, subtracts from mic input
- NS (Noise Suppression): removes ambient noise from cleaned audio
- BSS (Blind Source Separation): isolates human voice from residual noise
- `audio_capture_task()` — reads clean audio from pipeline, writes to WebSocket send buffer
- `audio_playback_task()` — reads received audio from WebSocket, writes to ES8311 speaker
- Playback tracking: sets flag when TTS audio starts, sends `playback_done` when buffer drains

**Key logic:**
- AEC reference loop: the same audio data sent to the speaker is simultaneously fed to the AEC algorithm as the reference signal. This is what enables echo cancellation.
- Pipeline runs continuously during ACTIVE/SPEAKING states, pauses during SLEEP.

### client/esp32/main/ws_client.c

**Purpose:** WebSocket client. Handles connection, authentication, and bidirectional message exchange.

**Contains:**
- WebSocket connection to server (configurable URL from NVS)
- Auth on connect: sends `{"type":"auth","token":"<device_token>"}` as first message
- Send: audio chunks (base64 encoded), JSON control messages (`wake`, `interrupt`, `playback_done`, `mode_switch`)
- Receive: audio chunks (decode + write to playback buffer), JSON control messages (`sleep`, `status`, `mode_changed`)
- Disconnect detection + reconnection with exponential backoff
- 60s grace period handling: if reconnect succeeds within window, session resumes

### client/esp32/main/wake_word.c

**Purpose:** On-device wake word detection using ESP-SR.

**Contains:**
- ESP-SR model initialization with custom wake phrase "Hi Vayumi"
- `wake_word_task()` — runs continuously during SLEEP state, listens for wake word
- On detection: sends `{"type":"wake"}` via WebSocket, starts audio pipeline streaming, transitions LED to blue
- Confidence threshold filtering to reduce false activations
- Works through speaker playback (AEC provides clean audio to the wake word detector)

### client/esp32/main/led.c

**Purpose:** RGB LED ring status control.

**Contains:**
- WS2812B LED driver (7 LEDs)
- Status patterns:
  - Dim/off: SLEEP (wake word listening)
  - Blue pulse: ACTIVE (listening for speech)
  - Yellow: PROCESSING (waiting for server response)
  - White stream: SPEAKING (TTS playing)
  - Red flash: error (WiFi disconnect, auth failure)
  - Green flash: boot/connect success

---

## server/data/vayumi.db

**Purpose:** SQLite database file. Created automatically on first run.

**Contains tables:**
- `users` — registered user accounts
- `reminders` — user reminders (per user_id)
- `meetings` — meeting records (per user_id)
- `contacts` — known speakers/contacts (per user_id)
- `memory_episodes` — summarized memory entries (per user_id)
- `injected_flags` — flag injection log (per user_id)

---

## server/data/vectordb/

**Purpose:** ChromaDB persistent storage directory. Created automatically.

**Contains:** ChromaDB's internal files for the `episodic_memory` collection. All entries have `user_id` in metadata for isolation.

---

## requirements.txt

**Purpose:** Python dependencies for the server.

**Contains:**
```
fastapi
uvicorn[standard]
websockets
chromadb
sentence-transformers
groq
google-generativeai
kokoro-onnx
bcrypt
PyJWT
python-multipart
numpy
silero-vad
speechbrain
torch
torchaudio
```

**Notes on dependencies:**
- `silero-vad`: ML-based VAD (streaming-capable). Alternative: `webrtcvad` (simpler, C-based, no ML). Choose one — the `VADEngine` implementation differs significantly.
- `speechbrain`: ECAPA-TDNN model for diarizer voice embeddings (~400MB download, ~200-400ms/inference on CPU). Good accuracy for owner-vs-guest.
- `torch` + `torchaudio`: required by both `silero-vad` and `speechbrain`. Install CPU-only build to save space: `pip install torch torchaudio --index-url https://download.pytorch.org/whl/cpu`
- `numpy`: required by TTS (PCM conversion), VAD, and diarizer.

---

## How Files Connect (Dependency Flow)

```
main.py
  ├── ws/handler.py  ← SINGLE ENTRY POINT for all WebSocket communication
  │     ├── auth/jwt_handler.py (connection auth)
  │     ├── voice/vad.py (echo-aware) → voice/stt.py → voice/diarizer.py (audio path)
  │     ├── core/context_builder.py (builds LLM context)
  │     ├── core/orchestrator.py (processes turns)
  │     │     ├── agents/task_agent.py ← skills/skill_runner.py, llm/router.py
  │     │     ├── agents/search_agent.py ← mcps/web_search.py, llm/router.py
  │     │     ├── core/mode_manager.py (per-session)
  │     │     ├── skills/skill_runner.py ← skills/*/
  │     │     ├── mcps/* (called via orchestrator validation)
  │     │     └── llm/router.py ← llm/groq_client.py, llm/gemini_client.py
  │     ├── agents/memory_agent.py ← memory/*, llm/router.py (background, async)
  │     ├── agents/persona_agent.py ← memory/sqlite_store.py (speaker labels)
  │     ├── core/interrupt_handler.py (stop/redirect, echo-aware)
  │     └── voice/tts.py (response streaming audio)
  ├── auth/router.py ← auth/jwt_handler.py, auth/models.py, memory/sqlite_store.py
  ├── core/context_builder.py
  │     ├── memory/vector_store.py ← memory/embedder.py
  │     ├── memory/sqlite_store.py
  │     ├── skills/skill_registry.json
  │     └── mcps/mcp_registry.json
  └── memory/ (initialized at startup: SQLite WAL mode, ChromaDB client)

ESP32-S3-AUDIO-Board (client-side, separate codebase):
  audio_pipeline.c (AEC+NS+BSS) → clean audio → ws_client.c → server
  wake_word.c (ESP-SR) → {"type":"wake"} → ws_client.c → server
  ws_client.c ← server audio → audio_pipeline.c → speaker (ES8311)
  led.c ← state changes from ws_client.c
```

Message flow through the handler:

```
Client connects → websocket_endpoint()
  → authenticate_connection() → Session created (activation_state=SLEEP, playback_state=IDLE)
  → message_loop():
      "wake"          → handle_wake → SLEEP→ACTIVE, start 30s timer
      "audio_chunk"   → handle_audio_chunk:
                           if SLEEP: ignore (no audio processing)
                           if ACTIVE: echo-aware VAD → STT → diarize → process_user_turn
                           if SPEAKING: echo-aware VAD → interrupt_handler (classify & handle)
      "text_input"    → handle_text_input → process_user_turn, reset timer
      "interrupt"     → handle_interrupt → stop TTS, playback_state=IDLE, ACTIVE
      "playback_done" → handle_playback_done → playback_state=IDLE, ACTIVE, reset timer
      "mode_switch"   → handle_mode_switch → mode_manager.switch
      "speaker_label" → handle_speaker_label → persona_agent

  process_user_turn (shared by voice + text):
      → context_builder.build()
      → orchestrator.run()
        → [if long task] returns ack/result payload; handler streams ack first, then result
        → [if deferred] task runs, result stored in memory, no response now
      → sets activation_state=SPEAKING, playback_state=PLAYING (caller owns state)
      → stream_response() → text + TTS audio (1-sentence lookahead for gap-free speech)
      → memory_agent.process_turn() (background, async)
      → _drain_input_queue():
          if any queued item is cancel intent → discard all
          otherwise → process only LAST queued item (most recent wins)

  Active window timeout (30s silence) → send {"type":"sleep"} → SLEEP
  Meeting mode: timeout disabled (stays ACTIVE for entire meeting)

  Client disconnects → cleanup_session() (cancel timers, release resources)
```

---

*Plan Version 1.4 — Added: input queue drain rules (cancel-discards-all / last-item-wins), TTS 1-sentence lookahead in stream_response, SpeechBrain ECAPA-TDNN specified as diarizer model with latency notes, torch/torchaudio as explicit dependencies, caller-owns-state clarification.*
*Previous: v1.3 — echo cancellation, wake word, Session object definition, ESP32 firmware plan*
*This plan covers every file needed for Phase 1, including basic ESP32-S3-AUDIO-Board firmware (WiFi, WebSocket, AEC pipeline, wake word). Advanced ESP32 features (OTA updates, battery management, LCD display) are Phase 2. Skills and MCPs beyond web_reader and web_search will be added in Phase 2 with no changes to any of the server files listed above.*
