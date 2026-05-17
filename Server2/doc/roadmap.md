# Vayumi Server 2 — Full Roadmap

**Source of truth:** [`PLAN.md`](../PLAN.md) v1.5  
**Architecture diagram:** [`orchestrator_diagram_v3.drawio`](../orchestrator_diagram_v3.drawio) (17 pages)  
**Progress tracker:** [`doc/tracker.md`](tracker.md)  
**Step details:** each step links to its `doc/step-NN.md` when that file exists.

> This file shows the big picture — every step, what it delivers, what files it touches, and what the user can do after it. For frozen architecture decisions see PLAN.md. For the full task list of a single step see its `step-NN.md` file.

---

## Status legend

| Symbol | Meaning |
|---|---|
| ⬜ | Not started |
| 🔄 | In progress |
| ✅ | Done (acceptance test passed) |

---

## Phase 1 — Spine

Goal: prove the architecture is real. By the end of Phase 1, you can talk to Vayumi from the web client, it understands you, replies in voice, remembers things, and uses one tool. No sub-agents yet.

---

### Step 1 — Project scaffold + WebSocket echo ✅

**File:** [`doc/step-01.md`](step-01.md)  
**Estimated effort:** 1 day  
**Diagram pages:** 01, 02, 03, 14

**What the user can do after this step:**
- Open a web page, type `dev` as the token, and connect via WebSocket (no Server 1 needed).
- Send a typed message and see it echoed back.
- Record 1 second of audio and see the binary echoed back.
- See invalid tokens rejected with code 4401.
- Optionally: set `JWT_PUBLIC_KEY` + `SERVER1_REDIS_URL` to test with real Server 1 tokens.

**Features delivered:**
- FastAPI + uvicorn app skeleton
- Postgres, Redis, LanceDB connection + health checks on boot
- Server 1 RS256 JWT verification + Redis blocklist check (with clean dev-mode bypass when Server 1 is not available)
- WebSocket endpoint `/ws/v1/session` with echo behavior
- Pydantic protocol models (Hello, Chat, AudioStart, AudioEnd, Ping / Welcome, Echo, Pong, Error)
- Reference web client (vanilla JS, single page)
- Unit tests for protocol parsing

**Files created:**

| File | Purpose |
|---|---|
| `pyproject.toml` | Dependencies + project metadata |
| `.env.example` | All env vars with descriptions |
| `.gitignore` | Standard Python + models/ + data/ |
| `docker-compose.dev.yml` | Optional local Postgres + Redis (cloud `.env` is typical) |
| `server/__init__.py` | Package marker |
| `server/app.py` | FastAPI app + lifespan (boot sequence) |
| `server/config.py` | Pydantic Settings, fail-fast validation |
| `server/logger.py` | structlog setup (JSON prod, pretty dev) |
| `server/auth.py` | `verify_token()` — RS256 + blocklist |
| `server/db/__init__.py` | Package marker |
| `server/db/postgres.py` | asyncpg pool + schema migration |
| `server/db/redis.py` | Redis asyncio client + ping |
| `server/db/lancedb.py` | LanceDB connect + writable check |
| `server/transport/__init__.py` | Package marker |
| `server/transport/ws.py` | WebSocket endpoint + echo loop |
| `server/transport/protocol.py` | Typed message envelopes |
| `web-client/index.html` | Reference client HTML |
| `web-client/client.js` | WS connect, send chat, record PCM |
| `tests/__init__.py` | Package marker |
| `tests/conftest.py` | Fixtures: fake JWT, event loop |
| `tests/unit/test_protocol.py` | Protocol round-trip tests |

**What is NOT in this step:** LLM, STT, TTS, VAD, wake word, memory behavior, tools, sub-agents, mobile/ESP32, production hardening.

---

### Step 2 — Engine plane ⬜

**File:** [`doc/step-02.md`](step-02.md) (stub — fill in before implementation)  
**Estimated effort:** 1–2 days  
**Diagram pages:** 02, 06

**What the user can do after this step:**
- Send a typed message and receive a streamed text reply from Gemma 3n E2B via the Main Agent (no voice yet, text captions only).

**Features delivered:**
- `llama-server` subprocess lifecycle (start, health check, restart on crash, stop)
- Priority queue with 4 slots: P0 (Main), P1 (sub-agents, unused yet), P2 (summarizer, unused yet)
- Slot 0 sticky for Main agent
- Main-only prompt assembly (system prompt + user message)
- Replace Echo handler with streamed `caption` events
- Web client shows captions as they arrive

**Files created / changed:**

| File | Purpose |
|---|---|
| `server/engine/__init__.py` | Package marker |
| `server/engine/runner.py` | llama-server subprocess lifecycle |
| `server/engine/pool.py` | Priority queue + slot manager |
| `server/engine/prompt.py` | Prompt template assembly |
| `prompts/main.txt` | Main Agent system prompt |
| `server/transport/ws.py` | CHANGED — chat now goes through engine |
| `server/transport/protocol.py` | CHANGED — add `Caption` server message |
| `web-client/client.js` | CHANGED — render streaming captions |

**What is NOT in this step:** Voice (STT/TTS), interrupt, memory, tools, sub-agents.

---

### Step 3 — Voice plane ⬜

**File:** `doc/step-03.md`  
**Estimated effort:** 2 days  
**Diagram pages:** 04, 10

**What the user can do after this step:**
- Speak into the mic, get a spoken reply from Vayumi.
- Interrupt the assistant mid-speech (button or wake word).
- See live captions while the assistant speaks.

**Features delivered:**
- Groq Whisper STT integration (streaming transcription)
- STTBackend interface for swappable backends
- Kokoro TTS streaming (sentence-level PCM)
- Silero VAD for server-side end-of-utterance detection
- Interrupt controller + speech state machine (LISTENING, THINKING, SPEAKING, IDLE)
- Binary PCM streaming to client (server -> client TTS audio)

**Files created / changed:**

| File | Purpose |
|---|---|
| `server/voice/__init__.py` | Package marker |
| `server/voice/stt/base.py` | STTBackend protocol |
| `server/voice/stt/groq.py` | Groq Whisper implementation |
| `server/voice/tts/kokoro.py` | Kokoro streaming TTS |
| `server/voice/vad/silero.py` | Silero VAD |
| `server/voice/interrupt.py` | Interrupt controller + FSM |
| `server/transport/ws.py` | CHANGED — binary audio routing |
| `server/transport/protocol.py` | CHANGED — add audio_start/end server msgs |
| `web-client/client.js` | CHANGED — playback queue, interrupt button |

---

### Step 4 — Web client v1 ⬜

**File:** `doc/step-04.md`  
**Estimated effort:** 1 day  
**Diagram pages:** 01, 04, 05

**What the user can do after this step:**
- Full voice conversation loop: speak -> hear reply -> interrupt -> speak again.
- Type messages alongside voice.
- See a proper UI: status indicator, captions, chat bubbles, activity feed area.
- client_state / client_control handshake works.

**Features delivered:**
- Polished single-page web client
- AudioWorklet-based mic capture (16kHz mono PCM)
- TTS playback queue with proper start/stop
- client_state reporting (playback, capture, visibility, audio route)
- client_control handling (play, pause, stop, duck, unduck)
- Mode switching UI (conversation / meeting stub)

**Files created / changed:**

| File | Purpose |
|---|---|
| `web-client/index.html` | CHANGED — polished UI |
| `web-client/client.js` | CHANGED — full audio pipeline, client_control |
| `web-client/style.css` | NEW — styling |
| `server/transport/client_control.py` | NEW — server-side client control |
| `server/transport/protocol.py` | CHANGED — add client_state, client_control, mode |

---

### Step 5 — Memory v1 ⬜

**File:** `doc/step-05.md`  
**Estimated effort:** 2 days  
**Diagram pages:** 09

**What the user can do after this step:**
- Say "remember my name is Alex" and have it stored as a versioned fact.
- Ask "what's my name?" and get the answer from memory.
- Update a fact and ask "what was my old name?" to see the supersession chain.
- The assistant's warm profile adapts to stored facts.

**Features delivered:**
- Postgres versioned facts: `set_fact()`, `get_fact()`, `get_chain()`
- Warm profile builder (~600 tokens, always in context)
- `[REMEMBER]` and `[RECALL]` directive handling
- Session history: `append_turn()`, `recent_turns()`, `compressed_history()`
- bge-small-en-v1.5 ONNX embedder loaded at boot
- LanceDB `facts_index` table with embeddings
- `schema.sql` expanded with facts, sessions, turns tables

**Files created / changed:**

| File | Purpose |
|---|---|
| `server/memory/__init__.py` | Package marker |
| `server/memory/facts.py` | Versioned fact CRUD |
| `server/memory/warm.py` | Warm profile builder + dirty flag |
| `server/memory/session.py` | Turn history + session state |
| `server/memory/retrieval.py` | LanceDB semantic query (stub, full in step 10) |
| `server/db/schema.sql` | CHANGED — add facts, sessions, turns tables |
| `server/db/lancedb.py` | CHANGED — create facts_index table |
| `server/orchestrator/__init__.py` | Package marker |
| `server/orchestrator/directives.py` | REMEMBER/RECALL parsing |
| `server/orchestrator/supervisor.py` | CHANGED — inject warm + history into context |
| `server/engine/prompt.py` | CHANGED — warm profile block in prompt |

---

### Step 6 — Tool plane ⬜

**File:** `doc/step-06.md`  
**Estimated effort:** 2 days  
**Diagram pages:** 08

**What the user can do after this step:**
- Ask "search for the latest AI news" and get results from Tavily/DDG.
- Main agent can call cheap direct tools (web_search, memory_recall, tool_search).
- Activity feed shows tool usage (started, done).

**Features delivered:**
- Tool registry with `ToolEntry` schema
- Tool runner with capability gate, timeout, audit
- `tool_search` discovery tool
- `web_search` (Tavily primary, DDG fallback)
- `memory_save` / `memory_recall` as registered tools
- `[DELEGATE]` directive parsing (ready for sub-agents, spawning deferred to step 7)
- `event{kind:tool_started}` / `event{kind:tool_done}` transport events

**Files created / changed:**

| File | Purpose |
|---|---|
| `server/tools/__init__.py` | Package marker |
| `server/tools/registry.py` | Tool catalog + capability routing |
| `server/tools/runner.py` | Execute + normalize + audit |
| `server/tools/tool_search.py` | Compact discovery tool |
| `server/tools/web_search.py` | Tavily + DDG fallback |
| `server/tools/memory_save.py` | Fact write via tool interface |
| `server/tools/memory_recall.py` | Fact read via tool interface |
| `server/orchestrator/directives.py` | CHANGED — add DELEGATE parsing |
| `server/orchestrator/supervisor.py` | CHANGED — tool dispatch for Main |
| `server/transport/protocol.py` | CHANGED — add event messages |
| `web-client/client.js` | CHANGED — render activity feed |

---

## Phase 2 — Multi-agent

Goal: sub-agents run in parallel, report back, and the proactive notifier surfaces results. Full memory retrieval and automatic compression.

---

### Step 7 — Sub-agent worker + signal bus ⬜

**File:** `doc/step-07.md`  
**Estimated effort:** 2–3 days  
**Diagram pages:** 07, 15, 16

**What the user can do after this step:**
- Ask a multi-step question and see it delegated to a sub-agent.
- See task progress in the activity feed.
- A sub-agent can pause and ask for clarification (NEEDS_INFO).
- User can cancel a running task.

**Features delivered:**
- `SubAgentWorker` — one ephemeral conversation per task
- `report()` schema (STEP, NEEDS_INFO, DONE, ERROR) with Pydantic validation
- Signal bus (asyncio queue, sub-agent -> supervisor)
- Task board (create, pause, resume, cancel, complete)
- `[ANSWER_TO]` directive for resuming paused tasks
- `[STOP_TASK]` directive for cancellation
- Worker checkpoint/restore for reconnect resilience
- Postgres tasks + signals tables

**Files created / changed:**

| File | Purpose |
|---|---|
| `server/subagents/__init__.py` | Package marker |
| `server/subagents/worker.py` | SubAgentWorker lifecycle |
| `server/subagents/report.py` | report() schema + validation |
| `server/orchestrator/signal_bus.py` | Async pub/sub for signals |
| `server/orchestrator/task_board.py` | Task state machine + render |
| `server/orchestrator/supervisor.py` | CHANGED — spawn/resume/cancel sub-agents |
| `server/orchestrator/directives.py` | CHANGED — ANSWER_TO, STOP_TASK |
| `server/engine/pool.py` | CHANGED — P1 slot allocation for sub-agents |
| `server/db/schema.sql` | CHANGED — add tasks, signals tables |

---

### Step 8 — Capability bundles ⬜

**Estimated effort:** 2 days  
**Diagram pages:** 08

**Features delivered:**
- 3 capability bundles: research, productivity, comms
- Per-capability prompts in `prompts/sub/`
- Tool access gates (sub-agent sees only its capability's tools)
- `load_capability()`, `render_tool_cards()`
- `summarize_url` tool (trafilatura)
- `fetch_html` tool

**Files created:** `server/subagents/capabilities/{research,productivity,comms}/manifest.py`, `prompts/sub/{research,productivity,comms}.txt`, `server/tools/summarize_url.py`, `server/tools/fetch_html.py`

---

### Step 9 — Proactive notifier ⬜

**Estimated effort:** 1–2 days  
**Diagram pages:** 11

**Features delivered:**
- Background loop drains signal bus when user is silent
- Importance threshold + min-interval debounce
- Synthetic turn pipeline (notifier -> handle_turn -> Main speaks)
- `notification` server message type
- Client shows notification toasts

**Files created:** `server/orchestrator/notifier.py`

---

### Step 10 — LanceDB retrieval ⬜

**Estimated effort:** 1 day  
**Diagram pages:** 09

**Features delivered:**
- Full semantic retrieval via LanceDB (top-k by query embedding)
- `memory_recall` tool upgraded to use semantic search
- `[RECALL doc:<doc_id>]` directive support
- Retrieval snippets with citations injected into context

**Files changed:** `server/memory/retrieval.py` (full implementation), `server/tools/memory_recall.py`, `server/orchestrator/directives.py`

---

### Step 11 — Summarizer ⬜

**Estimated effort:** 2 days  
**Diagram pages:** 09

**Features delivered:**
- P2 summarizer worker using the engine pool
- Automatic session compression when history exceeds 20k tokens
- Fact extraction from completed task results
- `prompts/summarizer.txt`

**Files created:** `server/memory/summarizer.py`, `prompts/summarizer.txt`

---

## Phase 3 — Modes & polish

Goal: meeting mode, offline fallback, file/image handling, MCP extensibility.

---

### Step 12 — Meeting mode ⬜

**Features delivered:**
- Meeting mode toggle (Main is dormant, transcript accumulates)
- Diarization-friendly chunked storage in LanceDB
- Post-meeting summary generation
- Meeting summary stored as a fact

---

### Step 13 — Local STT fallback ⬜

**Features delivered:**
- faster-whisper local STT backend
- Offline mode flag in config
- Automatic fallback when Groq is unreachable
- STTBackend interface swap is transparent

---

### Step 14 — Wake-word echo trap ⬜

**Features delivered:**
- Server-side detection of TTS audio leaking into mic
- Anti-self-trigger when Kokoro is playing
- Coordinated with client echo cancellation flag

---

### Step 15 — File/image upload + attachments ⬜

**Features delivered:**
- `POST /upload/v1/file` endpoint (images: 20MB, docs: 100MB)
- `chat.attachments[]` references uploaded files
- Attachment summarization (OCR, image caption, doc preview)
- Long-input ack within 300ms
- Chunked async document analysis via research sub-agent
- `event{kind:file_processing}` progress events

---

### Step 16 — MCP adapter ⬜

**Features delivered:**
- Connect arbitrary MCP servers declared in `config/mcp.json`
- Mirror MCP tools into the native registry on startup
- Subscribe to `tools/list_changed` for live re-mirroring
- Capability mapping (config-driven, default: `data`)

**Files created:** `server/tools/mcp_adapter.py`, `config/mcp.json`

---

## Phase 4 — Clients & deploy

Goal: mobile client, ESP32 hardware, production hardening, observability.

---

### Step 17 — Mobile reference client ⬜

**Features delivered:**
- React Native or Flutter reference app
- Same WS protocol as web client
- Native PCM socket, hardware AEC
- Push notification integration via Server 1

---

### Step 18 — ESP32 firmware ⬜

**Features delivered:**
- ESP32 smart speaker firmware
- `esp_websocket_client` WS connection
- Hardware AEC chip integration
- Wake word on device (openWakeWord ONNX)
- PCM audio streaming

---

### Step 19 — Production hardening ⬜

**Features delivered:**
- WebSocket backpressure + rate limiting
- Reconnection with session rehydration
- CORS lockdown + TLS
- Graceful shutdown with task draining
- Health check endpoint for load balancers

---

### Step 20 — Observability dashboard ⬜

**Features delivered:**
- OpenTelemetry traces (turn_id, task_id correlation)
- Structured JSON logs with trace context
- Metrics: latency histograms, slot utilization, tool call counts
- Simple dashboard (Grafana or web-based)

---

## Cross-step rules

These apply to every step. If a step violates any of them, it is not done.

1. The web client must still work after every step.
2. All acceptance tests from previous steps must still pass.
3. No architecture changes without updating PLAN.md.
4. No new dependencies without adding to pyproject.toml and the rejected-alternatives table if relevant.
5. Every step ends with a green `pytest` run.
6. If a step is tempted to pull in work from a later step, write it in the later step file instead.
