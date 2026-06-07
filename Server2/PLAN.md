# Vayumi Server 2 — Master Plan

**Version:** 1.7 (+ post-Step-10 amendments, see §7.10.1)  
**Status:** Architecture locked, Step 11 next (Steps 1–10 complete)  
**Last updated:** 2026-06-07  
**Companion files:** `doc/step-11.md` (current), `doc/roadmap.md`, `doc/tracker.md` (progress + flows + §Post-Step-10), `agent-prompt.md`  
**Reference diagrams:** `orchestrator_diagram_v3.drawio` (17 pages — architecture), `doc/tracker.md` (build progress + architecture flows)  
**Sister service:** `Server1/` (TypeScript) — owns auth, identity, sessions, push tokens. Already implemented and verified.

> **How to use this document:** This plan + the v3 diagram are the *complete* spec. If you (or any future agent) read these two end-to-end you have everything you need to build, debug, or extend Vayumi. If a question is not answered here, the answer is "open a step file or extend §7.9 / §7.10 / §7.11 / §13"; do not improvise.

---

## 0. Why this plan exists (read this first)

You have restarted Vayumi 10+ times. Every restart had the same root cause: **architecture decisions that were "I'll figure that out later"** later turned into blockers.

This plan freezes those decisions. From here on:

1. **No re-architecting.** If something is wrong, we write it as a new step, we do not throw the codebase away.
2. **Every step has a "done" definition.** A step is done when its acceptance test passes — nothing else.
3. **The client is built side-by-side, not last.** A 50-line web page that talks to the WebSocket exists from Step 1. App + ESP32 are swap-ins on the same protocol.
4. **One file owns each decision.** This `PLAN.md` is the only place where stack decisions live. Step files describe *what to build*, not *what to choose*.

If a decision feels uncertain, that means we did the research wrong — escalate, do not improvise.

---

## 1. What Vayumi is (one paragraph)

Voice-first multi-agent assistant. User talks (or types). A **Main Agent** running a local Gemma 3n model holds the conversation, owns speech, and delegates tool-heavy work to **Sub-Agents** that share the same model engine through a priority queue. Memory is layered (warm profile, on-demand retrieval, versioned facts). Sub-agents only speak through the Main Agent. Background tasks run in parallel; results surface as proactive notifications when the user is silent. Clients are interchangeable (web, mobile app, ESP32 hardware) because the stable contract is one WebSocket session protocol plus a small upload endpoint for files/images.

### 1.1 Two-server topology

Vayumi is **two cooperating services**, on purpose:

```
              ┌──────────────────────────┐                    ┌──────────────────────────┐
   client ── ▶│  Server 1 (TypeScript)   │  RS256 JWT  ─────▶│   Server 2 (Python)       │
              │  identity & accounts      │  shared Redis      │   Vayumi orchestration    │
              │  /auth/login,/register…  │  blocklist (jti)   │   /ws/v1/session          │
              │  push tokens, sessions   │  (read-only)       │   voice + agents + tools  │
              └──────────────────────────┘                    └──────────────────────────┘
                       │                                                    │
                       └──────── Postgres + Redis (shared infrastructure)──┘
```

- **Server 1** is the source of truth for *who the user is*. Login, register, profile, push tokens, OAuth integrations to external services (gmail/calendar/drive/notion), sessions and refresh-token rotation all live there. Server 2 has no opinion about any of that.
- **Server 2** is the source of truth for *what the assistant does*. WebSocket transport, voice pipeline, the Main Agent + Sub-Agents, tools, memory, MCP, summarizer.
- **The contract between them** is exactly two things:
  1. Server 2 verifies access tokens **offline** with Server 1's RS256 public key (no API call per request).
  2. Server 2 reads Server 1's Redis `blocklist:<jti>` keys to honor revocations.
- Server 2 **never** writes to Server 1's tables. Server 2 stores its own data (facts, conversations, tasks, signals) in its own Postgres schema.

> **You do not need to think about auth while building Server 2.** Pretend every WebSocket connection arrives with a verified `user_id`. Section 2 row "Auth" describes the 30 lines of code that make that pretense true.

---

## 2. The full stack — frozen decisions

| Layer | Choice | Why this and not alternatives |
|---|---|---|
| **Server framework** | **FastAPI + uvicorn (asyncio)** | Native async, native WebSocket, fits the supervisor/event-loop model. No surprises. |
| **Local LLM** | **Gemma 3n E2B (instruction-tuned), 4-bit GGUF, 32k ctx** | E2B is small enough for CPU, real instruction-following. **NOT FunctionGemma 270M** — research shows it scores 9–38% on multi-turn tool calling without fine-tuning, which is exactly what bit you last time. We use Gemma 3n E2B as the brain for both Main and Sub-agents and let the orchestrator parse directive blocks (`[DELEGATE]`, `[STOP]`, etc.) from its text output. If a 270M function-caller becomes useful later it slots in as a *router*, not the brain. |
| **LLM runtime** | **llama.cpp server (HTTP) + thin Python client** | Native multi-slot parallel decoding (`-np 4`) gives us the "shared engine" from page 9 of the diagram for free. KV-cache reuse per slot. OpenAI-compatible `/completion` endpoints. Loading the model once, serving 4 conversations (Main + 2 sub-agents + summarizer) is exactly its happy path. We do **not** use `llama-cpp-python` directly because its server has weaker multi-slot support; we run the C `llama-server` binary as a subprocess and talk HTTP to it. |
| **Engine pool** | **Single `llama-server` process, 4 parallel slots, priority queue in our Python code** | Our queue picks which request goes next; `llama-server` handles the parallel decode. Main = slot 0 (sticky), sub-agents grab any free slot, summarizer gets the lowest priority. |
| **STT** | **Groq Whisper API (primary) + faster-whisper local (fallback)** | Groq Whisper is ~300ms p95 and free tier is enough for dev. faster-whisper-tiny on CPU as the offline fallback so the system still works without network. Both behind one `STTBackend` interface. |
| **TTS** | **Kokoro via `pykokoro` (ONNX, streaming)** | RTF 0.03 on GPU, still real-time on CPU for the small model. Streams sentence-level PCM. Already chosen — we keep it. |
| **VAD** | **Silero VAD (ONNX, ~2 MB)** | More accurate than WebRTC VAD, still tiny. Used both for end-of-utterance and for client-local interrupt cues. |
| **Wake word** | **openWakeWord** with the existing custom "Vayumi" ONNX model | You already trained it; no reason to re-do. Runs client-side on web/app/ESP32. The server never does wake detection — that's the client's job to save bandwidth. |
| **Transport** | **WebSocket for session/audio/control + signed HTTPS upload endpoint for large files** | Plain WS works on browser, mobile, and ESP32. Binary WS frames remain audio-only so the server can stream low-latency PCM without ambiguity. Files/images use an upload endpoint that returns `file_id`; the chat message references that id. Echo cancellation is the *client's* responsibility; the server assists via `client_control` commands (see §5.5). |
| **Memory** | **Hybrid: Postgres (versioned facts + sessions) + LanceDB (embedded, semantic retrieval)** | Postgres gives ACID, versioned chains, and superseded history exactly as your diagram needs. LanceDB is a single Python import, disk-backed, scales to millions of vectors, and its versioning maps cleanly to your "superseded fact" model. **No external memory framework** (Mem0/Letta/Zep/MemoryOS) — we own the schema, we own the API, we never get blocked by an upstream library decision. mem0's *fact extraction prompt* is good prior art and we will borrow that pattern. |
| **Embeddings** | **`bge-small-en-v1.5` via `sentence-transformers` ONNX** | 33M params, runs on CPU in milliseconds, MIT-licensed, top of the small-model leaderboard. |
| **Tools** | **Native Python tool registry first, MCP adapter second** | A tool is a typed async Python function with JSON args and a normalized `ToolResult`, registered through `tools/registry.py`. We add an **MCP client adapter** (using the official `modelcontextprotocol` Python SDK) so any MCP server (filesystem, GitHub, Notion, etc.) shows up as tools without touching agent code. This gives you "easy to add anything" with zero lock-in. |
| **Web search tool** | **Tavily** (free tier 1k/mo) with **DuckDuckGo HTML scrape** as a no-key fallback | Tavily already returns clean snippets; DDG fallback means dev never blocks on API keys. |
| **HTML scraping** | **trafilatura** (best-in-class for article extraction in 2026) | Used by the `summarize_url` sub-agent tool. |
| **Auth** | **Trust Server 1's JWT, nothing else.** Verify RS256 signature offline + check shared Redis blocklist. **Dev bypass:** when `APP_ENV=dev` and `JWT_PUBLIC_KEY` is not set, accept token `"dev"` and return a fixed dev user. No separate flag, no second code path — just env presence. | Server 1 already owns login, register, password reset, OAuth, sessions, push tokens. Server 2's auth is **30 lines of code** (`server/auth.py`): decode token → validate exp/iat/claims → `GET blocklist:<jti>` in shared Redis → return `TokenPayload(user_id, session_id, scopes)`. After that, every WebSocket connection has a verified `user_id` and Server 2 *never thinks about auth again*. We wire this in Step 1 once and forget. There is no user table on Server 2. There is no login endpoint on Server 2. There is no password code on Server 2. If a token expires mid-session, server emits `event{kind:'token_expiring'}` 5 minutes before exp; client refreshes against Server 1 and reconnects with the same `session_id`. |
| **Datastore** | **Postgres (Supabase) + Redis (shared with Server 1) + LanceDB (local file)** | Postgres for facts/sessions/conversations. Redis for the JWT blocklist + signal bus + pub/sub between proactive notifier and orchestrator. LanceDB is a folder on disk for vectors. |
| **Async runtime** | **`asyncio` only**. No threads, no multiprocessing for orchestration | Keeps the model simple. The `llama-server` binary is the only subprocess we manage. |
| **Logging** | **structlog + OpenTelemetry-friendly JSON** | Every turn gets a `turn_id`. Every sub-agent gets a `task_id`. Every signal carries both. You can `grep turn_id=xxx` and see the entire flow. |
| **Tests** | **pytest + pytest-asyncio + a recorded-LLM fixture** | We record `llama-server` responses for fixed prompts and replay them in CI so tests don't need a model. |
| **Frontend reference client** | **Plain HTML + vanilla JS in `web-client/index.html`** | Single file. ~150 LoC. Demonstrates: mic capture, WS connect, PCM upload, audio playback, captions, interrupt button, chat box. No framework, no build step. **This is the "we won't get stuck on the client at the end" guarantee.** |

### Multimodal inputs — deferred

Gemma 3n E2B natively supports image, audio, and video inputs via its vision encoder (MobileNetV5) and audio encoder (USM). However, the current GGUF builds available on HuggingFace (`ggml-org/gemma-3n-E2B-it-GGUF`) are **text-only**. llama.cpp has merged vision support (PR #18256, Jan 2026) but it requires a separate `--mmproj` GGUF file that is not yet stable for server-mode multi-slot use.

**Decision:** We start with text-only GGUF. The system handles voice through the STT/TTS pipeline (audio -> Whisper -> text -> LLM -> text -> Kokoro -> audio), not through native model audio input. Image, video, and audio-as-model-input are deferred — the approach (tool-based processing vs native multimodal GGUF) will be decided later based on upstream GGUF progress.

**Upgrade path when ready:** Add `--mmproj <file>.gguf` to the `llama-server` startup command in `engine/runner.py`. Zero architecture changes — the upload endpoint, tool pipeline, and sub-agent system all remain valid regardless of whether the LLM sees images natively or via tool-generated text descriptions.

### What we explicitly say no to

| Rejected | Why |
|---|---|
| LangGraph / CrewAI / AutoGen | They impose their own state model. Your diagram already specifies the state model. We'd spend more time fighting the framework than writing the orchestrator. The orchestrator we need is < 800 LoC. |
| Pipecat | Pipeline abstraction is wrong for our supervisor model. Sub-agent reports do not fit a linear pipeline. |
| LiteRT | Painful Python multi-conversation story. llama.cpp is mature, native, faster, has slots. |
| LangChain | Not needed. We are not chaining prompts; we are running an agent loop. |
| MemoryOS | Yet-another-memory-framework with weak versioning. We own this. |
| ChromaDB | In-memory. Won't survive a restart cleanly. LanceDB is strictly better at the same effort. |
| WebRTC for v1 | ESP32 client makes WebRTC painful. WS is enough. We design for swappability. |

---

## 3. Architecture — the seven planes

These are the same as the diagram, restated in code-level terms.

### 3.1 Transport plane (`server/transport/`)
- One WebSocket endpoint: `/ws/v1/session`.
- One upload endpoint: `POST /upload/v1/file` for user files/images. It returns a `file_id` used in WebSocket `chat.attachments`.
- One message envelope (binary frames for audio, JSON frames for everything else — see Section 5).
- Owns: connection lifecycle, auth handshake, ingress audio framing, egress audio frame schedule, heartbeat.
- Does **not** know about LLMs, tools, memory.

### 3.2 Voice plane (`server/voice/`)
- `stt/`: pluggable STT (`GroqWhisper`, `LocalFasterWhisper`).
- `tts/`: Kokoro streamer that emits 20 ms PCM frames.
- `vad/`: server-side end-of-utterance detection (Silero) — **only** for typed-as-audio scenarios; client should already do VAD.
- `interrupt.py`: a single class that owns the speech state machine (`SPEAKING`, `STOPPED`, `QUEUED`, `RESUMED`).

### 3.3 Engine plane (`server/engine/`)
- `runner.py`: starts/stops the `llama-server` subprocess.
- `pool.py`: priority queue (`P0` Main, `P1` sub-agents, `P2` summarizer) that calls `llama-server`'s `/completion` endpoint with the right slot id.
- `prompt.py`: builds the prompt for each role from the role's prompt template + injected context block. The Main Agent prompt is in `prompts/main.txt`. Each capability has its own sub-agent prompt in `prompts/sub/<capability>.txt`.

### 3.4 Orchestrator plane (`server/orchestrator/`)
- `supervisor.py`: the per-session brain. One instance per `user_id` (session singleton — see §5.0). The WebSocket is reattached via `attach_transport()` on reconnect or device handover; sub-agents stay bound to the Supervisor, not the socket.
- `directives.py`: parses `[DELEGATE]`, `[STOP_TASK]`, `[ANSWER_TO]`, `[RESPOND_VIA]`, `[REMEMBER]`, and `[RECALL]` blocks from Main's stream. **Discarded if interrupt fires mid-block** (page 9 of the diagram, "interrupt safety guarantee").
- `signal_bus.py`: in-process asyncio queue for sub-agent → main signals (`STEP`, `NEEDS_INFO`, `DONE`, `ERROR`).
- `notifier.py`: background loop that drains the signal bus and fires synthetic turns when the user is silent.
- `task_board.py`: the canonical structure that goes into context for Main on every turn — running tasks, latest signals, blocked tasks.

### 3.5 Sub-agent plane (`server/subagents/`)
- `worker.py`: one ephemeral conversation per task. Uses an engine slot. Sees only its capability's tools. Output schema is locked: it must call `report(STEP|DONE|NEEDS_INFO|ERROR, payload)`.
- `capabilities/`: one folder per capability bundle (`research/`, `productivity/`, `comms/`, `data/`). Each declares which tools it owns and a sub-agent prompt.

### 3.6 Tool plane (`server/tools/`)
- `registry.py`: one place where every tool is registered as a `ToolEntry` (`fn`, args schema, result schema, capability, auth, risk, confirmation policy).
- `tools/web_search.py`, `tools/memory_*.py`, `tools/summarize_url.py`, etc. — each is a typed async function returning `ToolResult`. They do not know they live inside an LLM.
- `mcp_adapter.py`: connects to configured MCP servers, mirrors their tools into the registry on startup, refreshes on `tools_changed` notifications.

### 3.7 Memory plane (`server/memory/`)
- `facts.py`: versioned-fact CRUD on Postgres. `set_fact(key, value)` archives the previous and writes a new active row. `get_chain(key)` returns the supersession history.
- `warm.py`: builds the always-in-context profile block (~600 tokens). Has a `dirty` flag set whenever a profile-affecting fact changes.
- `retrieval.py`: LanceDB queries. Returns top-k snippets with citations. Called only when the orchestrator decides retrieval is needed.
- `summarizer.py`: a P2 worker that compresses old turns and extracts new facts.
- `session.py`: rolling raw turns + compressed summaries per session.

---

## 4. Folder structure (this is the file tree you will create)

```
Server2/
├── PLAN.md                          this file — frozen decisions
├── doc/
│   ├── step-NN.md                   one file per step; current = first ⬜ in §8
│   ├── step-02.md                   example: next step after step 1
│   └── ...
├── README.md                        the user-facing pitch you wrote
├── pyproject.toml                   package + deps
├── .env.example
├── docker-compose.dev.yml           postgres + redis for local dev
├── models/                          (gitignored) ggufs + onnx live here
│   ├── gemma-3n-e2b-it-q4_k_m.gguf
│   ├── kokoro/
│   ├── silero-vad.onnx
│   └── bge-small-en-v1.5.onnx
├── prompts/
│   ├── main.txt
│   ├── summarizer.txt
│   └── sub/
│       ├── research.txt
│       ├── productivity.txt
│       ├── comms.txt
│       └── data.txt
├── server/
│   ├── app.py                       FastAPI + lifespan (boots engine, db, redis, registry)
│   ├── config.py                    pydantic-settings, fails fast on missing env
│   ├── auth.py                      verify Server 1 JWT, blocklist check
│   ├── logger.py                    structlog setup
│   ├── transport/
│   │   ├── ws.py                    WebSocket endpoint + envelope codec
│   │   ├── protocol.py              JSON message types (typed)
│   │   ├── session_registry.py      user_id → UserSession singleton
│   │   ├── session_busy.py          playback grace + chat_should_queue
│   │   ├── turn_coordinator.py      shared chat/voice/proactive delivery
│   │   ├── chat_queue.py            typed-chat queue + background compute
│   │   ├── uploads.py               upload endpoint, validation, file_id creation
│   │   └── client_control.py        server -> client playback / capture commands
│   ├── voice/
│   │   ├── stt/
│   │   │   ├── base.py              STTBackend protocol
│   │   │   ├── groq.py
│   │   │   └── local.py             faster-whisper
│   │   ├── tts/
│   │   │   └── kokoro.py            streaming PCM generator
│   │   ├── vad/
│   │   │   └── silero.py
│   │   └── interrupt.py
│   ├── engine/
│   │   ├── runner.py                llama-server subprocess lifecycle
│   │   ├── pool.py                  priority queue + slot manager
│   │   └── prompt.py                prompt assembly
│   ├── orchestrator/
│   │   ├── supervisor.py
│   │   ├── directives.py
│   │   ├── signal_bus.py
│   │   ├── notifier.py
│   │   ├── task_board.py
│   │   ├── tool_dispatch.py         main + sub-agent tool execution
│   │   ├── tool_fallback.py         model-output safety nets (no user-keyword routing)
│   │   └── prose.py                 spoken-output sanitization
│   ├── subagents/
│   │   ├── worker.py
│   │   ├── report.py                 report() schema + Pydantic validation
│   │   └── capabilities/
│   │       ├── research/
│   │       ├── productivity/
│   │       ├── comms/
│   │       └── data/
│   ├── tools/
│   │   ├── registry.py
│   │   ├── runner.py                 execute tool calls + normalize ToolResult
│   │   ├── tool_search.py            compact capability-aware discovery
│   │   ├── web_search.py
│   │   ├── summarize_url.py
│   │   ├── memory_save.py
│   │   ├── memory_recall.py
│   │   └── mcp_adapter.py
│   ├── memory/
│   │   ├── facts.py
│   │   ├── warm.py
│   │   ├── retrieval.py
│   │   ├── summarizer.py
│   │   └── session.py
│   └── db/
│       ├── postgres.py              asyncpg pool
│       ├── redis.py                 redis-py asyncio client
│       ├── lancedb.py
│       ├── schema.sql               raw SQL migrations
│       └── migrations/
├── web-client/                      ← reference client, kept ALIVE every step
│   ├── index.html                   single file, ~150 LoC
│   ├── client.js
│   └── style.css
└── tests/
    ├── conftest.py                  recorded-LLM fixture, in-memory queues
    ├── unit/
    └── integration/
```

---

## 5. The WebSocket protocol — frozen so the client never breaks

One endpoint: `wss://server2.example.com/ws/v1/session?token=<jwt>`.

### 5.0 Session singleton — one active connection per user

A user (`user_id`) may have **at most one active WebSocket connection** at any time across all clients (web, mobile, ESP32). This is not a limitation — it is the feature that makes the assistant feel like one coherent voice across all devices.

**Why one session:**
- Sub-agents, the task board, memory, and voice state are all per-session. Two simultaneous connections would require all of that to be shared, which adds complexity and split-brain risk with no UX benefit.
- The user cannot be in two places at once. If their phone connects, their laptop session should yield.

**Connection lifecycle rules:**

| Scenario | What happens |
|---|---|
| New connection, same `user_id`, no existing session | Normal connect. New `session_id` created. `welcome` sent. |
| New connection, same `user_id`, existing session, **different** `session_id` in `hello` or none | **Device handover.** Server sends `event{kind:'session_superseded', reason:'new_device'}` on the OLD connection and closes it (code 4001). Supervisor reattaches to the NEW connection with the **same** `session_id`, same task board, same in-flight tasks, same memory. New client gets `welcome{session_id, resumed:true}`. |
| New connection, same `user_id`, same `session_id` in `hello` | **Reconnect** (same device, network drop). Old connection is already gone. Supervisor reattaches to new socket. Client gets `welcome{session_id, resumed:true}`. History, task board, warm profile all intact. |
| New connection, different `user_id` | Separate session, no interference. |
| Old connection sends a message after receiving `session_superseded` | Server ignores it. Connection is already in close handshake. |

**In-flight tasks on device handover:** Sub-agent workers are running as asyncio tasks bound to the Supervisor, not to the WebSocket connection. Device handover rebinds the Supervisor to a new socket; sub-agents continue running without interruption. The new client receives the current task board in `welcome{task_board_snapshot}` so it can render the activity feed immediately.

**Implementation note:** The Supervisor registry in `server/transport/ws.py` maps `user_id → Supervisor`. On new connection for an existing `user_id`, the registry finds the live Supervisor, calls `supervisor.attach_transport(new_ws)`, and the old socket is closed cleanly. No state is duplicated.

### 5.1 Message envelope

- **Binary frames** = raw 16-bit PCM mono 16 kHz audio. Always direction is implicit: client→server is mic, server→client is TTS.
- **Text frames** = JSON. Every JSON message has exactly two top-level fields: `type` and `payload`.

### 5.2 Client → server JSON types

| `type` | `payload` | Meaning |
|---|---|---|
| `hello` | `{ client: "web"\|"ios"\|"android"\|"esp32", capabilities: { aec: bool, vad: bool, wake: bool, tts: bool }, session_id?: str }` | Sent first. `capabilities.tts=false` means this client has no speaker — server will default to `chat_only` for all responses. Server replies with `welcome`. |
| `chat` | `{ text: string, attachments?: [{file_id, kind, mime, name, size_bytes}] }` | Typed message, optionally referring to uploaded files/images. Server responds voice+chat by default (see §7, Rule 11). |
| `audio_start` | `{ sample_rate: 16000, format: "pcm_s16le" }` | Mic stream starting; binary frames follow. |
| `audio_end` | `{}` | End of utterance (client-side VAD decided so). |
| `interrupt` | `{ source: "wake"\|"button"\|"voice" }` | Stop current speech immediately. Background tasks keep running. |
| `mode` | `{ mode: "conversation"\|"meeting" }` | Switch mode. |
| `client_state` | `{ playback: "idle"\|"playing"\|"paused", capture: "idle"\|"recording", visible: bool, route?: "speaker"\|"earpiece"\|"bluetooth"\|"none" }` | Client tells server what the UI/audio layer is doing. Sent on every change. Server uses this to make `respond_via` decisions (see §7, Rule 13). |
| `ping` | `{ t: int }` | Heartbeat. |

### 5.3 Server → client JSON types

| `type` | `payload` | Meaning |
|---|---|---|
| `welcome` | `{ session_id, server_version, resumed: bool, task_board_snapshot? }` | Reply to `hello`. `resumed:true` means an existing session was found. `task_board_snapshot` contains current running/paused tasks for the client to render immediately. |
| `caption` | `{ text, partial: bool, turn_id }` | Text of what TTS is about to speak or is speaking. Sent sentence-by-sentence BEFORE the corresponding audio frames. Always sent regardless of `respond_via` — even `chat_only` turns emit captions so the user sees the text. |
| `chat_message` | `{ text, turn_id, final: bool }` | Full text of the assistant's response for display in the chat UI. Sent once when the complete response is assembled. Distinct from `caption` (which is sentence-level and TTS-synchronized); `chat_message` is the canonical text record. |
| `audio_start` | `{ sample_rate, format, turn_id }` | TTS stream starting; binary frames follow. Only emitted when `respond_via` includes voice. |
| `audio_end` | `{ turn_id }` | TTS done for this turn. |
| `client_control` | `{ command: "play"\|"pause"\|"stop"\|"duck"\|"unduck"\|"clear_queue"\|"start_capture"\|"stop_capture", reason, turn_id? }` | Server asks the client to control local playback/capture. Client confirms by sending `client_state`. |
| `event` | `{ kind: "tool_started"\|"tool_done"\|"task_step"\|"task_done"\|"task_error", task_id, summary }` | UX event for the activity feed. |
| `notification` | `{ task_id, text }` | Proactive surface (sub-agent finished while user was idle). |
| `error` | `{ code, message }` | Server-side error the user should know about. |
| `pong` | `{ t }` | Heartbeat reply. |

### 5.4 File and image upload contract

Binary WebSocket frames are audio-only. User files/images go through an upload endpoint, then get referenced from a `chat` message.

| Endpoint / message | Payload | Meaning |
|---|---|---|
| `POST /upload/v1/file` | multipart file + JWT | Stores the bytes, validates size/MIME, returns `{file_id, kind, mime, name, size_bytes, sha256}`. |
| `chat.attachments[]` | `{file_id, kind, mime, name, size_bytes}` | Tells the Supervisor to include the uploaded asset in the turn. |
| `event{kind:"file_processing"}` | `{file_id, status, summary}` | Lets the client show OCR/transcription/chunking progress. |

Upload rules:
- Images: `image/png`, `image/jpeg`, `image/webp`, max 20 MB.
- Documents: PDF, TXT, MD, CSV, DOCX later, max 100 MB.
- Audio/video files are accepted later for meeting/import mode, not Step 1.
- Uploaded files are not automatically memory. A file enters memory only if Main emits `[REMEMBER]` or a sub-agent returns `facts_to_persist`.
- Image understanding is a tool/capability issue. The transport layer only stores and references bytes.

### 5.5 Text and caption delivery contract

This section defines exactly when text appears, in what form, and what happens if TTS fails. These rules apply to **every** response regardless of whether it was triggered by voice or typed chat.

**Two text channels, both always sent:**

1. **`caption` events** — sentence-by-sentence, TTS-synchronized. Sent BEFORE the corresponding audio frames begin for that sentence. This is what the client displays as live captions during TTS playback.

2. **`chat_message` event** — the full assembled response, sent once when the complete LLM output is known. This is the persistent chat UI record. It is sent regardless of `respond_via` — even a `chat_only` turn (no TTS) emits a `chat_message`.

**Why both:**
- `caption` lets the client animate text in sync with speech, word by word, sentence by sentence.
- `chat_message` ensures the user always has the full text available even if they missed the captions, TTS failed, or they are in a chat-only context.

**Ordering within a turn:**

```
LLM streams sentence 1 text
  → emit caption{text:"sentence 1", partial:false, turn_id}
  → send audio_start{turn_id}
  → stream binary PCM frames for sentence 1
LLM streams sentence 2 text
  → emit caption{text:"sentence 2", partial:false, turn_id}
  → stream binary PCM frames for sentence 2
...
LLM output complete
  → emit audio_end{turn_id}
  → emit chat_message{text:"full response", turn_id, final:true}
```

**If TTS fails mid-response:**
- `audio_end{turn_id, error:true}` is emitted immediately.
- All `caption` events already sent remain visible to the user — text is not lost.
- `chat_message` is still emitted with whatever text was generated so far.
- Server sends `client_control{command:"clear_queue", reason:"tts_error"}` so the client discards any buffered audio.
- Main does not regenerate — the text the user saw in captions is the response. If the user asks again, they get a fresh response.

**If interrupt fires mid-TTS:**
- `audio_end{turn_id, interrupted:true}` is emitted.
- `caption` events already sent stay on screen (client may grey them out or not — its choice).
- `chat_message` is emitted with the text up to the interrupt point. Partial response is marked with `final:false`.
- Server sends `client_control{command:"clear_queue", reason:"interrupted"}`.
- The queue of pending TTS sentences (not yet played) is discarded. They are NOT spoken after the interrupt. The interrupted turn is over.

**Queue depth for typed chat:**
- A user may type multiple messages rapidly. The TTS queue depth is **1 pending** item beyond what is currently playing.
- If a third message arrives while one is playing and one is pending: the pending item is replaced by the new one. The new message's text enters the chat history normally but the superseded pending audio is dropped.
- This prevents a backlog of stale responses playing after a user has moved on.
- Voice interrupts always take priority and clear the entire queue regardless of depth.

---

## 6. Running budget for one turn (the latency target)

| Stage | Target p95 | Owner |
|---|---|---|
| WS audio in → STT first partial | 200 ms | Groq |
| STT final → orchestrator turn-start | 50 ms | server |
| Context assembly (warm + tasks) | 50 ms | orchestrator |
| Main LLM first token | 400 ms | engine |
| First TTS sentence ready | 200 ms | kokoro |
| First audio frame to client | 100 ms | transport |
| **End-to-end first audio** | **≈ 1.0 s** | combined |

Typed chat turns follow the same budget for first TTS sentence (the text rendering is instant; the latency budget is the same). If we miss this on a normal turn, that's a regression and a new step is opened to fix it. Long-input turns get the "I got it, processing in chunks" ack within 300 ms (page 2 of the diagram, "long-input protection").

---

## 7. The key behavioral contracts (from the diagram, restated as rules)

These rules are non-negotiable. Every step inherits them.

1. **Main owns speaking.** Sub-agents have no transport access. They `report()` only.
2. **Sub-agents see only their capability's tools.** Never the whole tool registry.
3. **Interrupt discards the directive buffer.** If `[DELEGATE]` was half-generated, it dies. No ghost tasks.
4. **Compression runs after the response, never before.** First token to user is sacred.
5. **Facts are versioned, never overwritten.** Old value goes to `superseded_by`, new value becomes active.
6. **Retrieval is on-demand.** It enters context only when the orchestrator explicitly asks.
7. **The proactive notifier uses the normal turn pipeline.** A `DONE` signal becomes a synthetic user turn; Main decides if/what to say.
8. **One engine for everything.** Main, sub-agents, summarizer share one `llama-server` process via the priority queue.
9. **Every tool announces intent before it runs.** UX rule: the user always knows what's happening. The `event{kind:'tool_started'}` fires before the tool executes.
10. **Every step ships with the web client working.** No "we'll integrate the client later."
11. **Typed chat triggers voice by default.** When a user sends a `chat` message, the server responds with `respond_via=voice_and_chat` unless the session is voice-incapable or a blocking condition applies (see Rule 13). Typing something does not mean the user wants a silent response — the assistant speaks and shows the caption. If the user is on a device with a speaker, they hear the reply.
12. **Echo suppression via `client_control` is mandatory for ALL TTS, regardless of what triggered it.** Before any `audio_start` frame is sent, the server emits `client_control{command:'stop_capture', reason:'tts_start'}`. After `audio_end` plus the echo suppression delay (default 1.2 s), the server emits `client_control{command:'start_capture'}`. This prevents the AI's own voice from being fed back as user input. This rule applies whether the turn was triggered by a voice command, a typed chat message, or a proactive notification. No exceptions.
13. **`respond_via` is computed per turn from session state, not from input kind alone.** See the full decision table in §7.5.

### 7.5 Agent vs Sub-agent — the exact capability split

This is the table the rest of the plan keeps referring to. It is locked. Whenever you add a new capability or tool, decide its row before writing code.

| Capability / Permission | Main Agent | Sub-agent | Notes |
|---|---|---|---|
| Speak to user (TTS audio) | ✅ owns it exclusively | ❌ never | Main is the only voice in the room. |
| Stream captions / chat text to user | ✅ | ❌ (uses `report()` only) | Sub-agents *cannot* surface text directly. |
| Receive client interrupts | ✅ (FSM owner) | ❌ | Interrupts cancel Main's stream, never sub-agents. |
| Decide when to surface a result | ✅ | ❌ | Main + Notifier decide if/when DONE/NEEDS_INFO becomes a user-visible turn. |
| Hold conversation history | ✅ (slot 0, sticky KV) | ❌ (ephemeral, dies with task) | Sub-agent context never bleeds into Main. |
| `web_search` (Tavily/DDG) | ✅ direct, fast | ✅ also available inside `research` capability | Cheap. Both can search. |
| `memory_recall` (read facts / chains) | ✅ | ✅ | Both can read what the user said before. |
| `memory_save` (write a fact) | ✅ via `[REMEMBER …]` directive (only on explicit user intent) | ✅ via `report(DONE, payload={facts:[…]})` (post-task summarizer extracts) | Two write paths, both go through `memory.facts.set()`. |
| `summarize_url`, `fetch_html`, `read_pdf`, OCR, parse_csv | ❌ never directly | ✅ research / data | Heavy / multi-step / parser-fragile work. Pollutes Main context. |
| Multi-step research, comparison, synthesis | ❌ never directly | ✅ research | Main delegates the *whole* multi-step job, gets back a condensed summary. |
| Email read/send, calendar, contacts | ❌ | ✅ comms | Requires Server 1 OAuth credentials; sub-agent fetches them via the auth-broker tool. |
| Filesystem / Notion / Drive / GitHub (MCP) | ❌ | ✅ productivity / data | Anything coming through the MCP adapter goes to sub-agents by default. |
| Long-document chunking + hierarchical summary | ❌ | ✅ research | The "long-input" mode delegates to a research sub-agent. |
| Meeting transcript summarization | ❌ during meeting | ✅ post-meeting | Main is dormant during meeting mode. |
| Spawn another sub-agent | ❌ | ❌ (only Main / Supervisor can) | Sub-agents are leaves of the task tree. No recursion. Prevents fan-out blow-ups. |
| Cancel a running task | ✅ via `[STOP_TASK …]` directive | ❌ | Only Main / Supervisor can cancel. |
| Talk to other sub-agents directly | ❌ | ❌ | All cross-task coordination goes through Main + task_board. |
| See its own capability's tool schemas | n/a (sees capability *labels* only) | ✅ | Sub-agent prompt is loaded with **only** its capability bundle. Minimum context. |
| Be persisted across restarts | n/a (recreated from session row) | n/a (task row keeps `status='running'` flag, see §13.11) | A long-running task can outlive a restart in *concept*, but its in-flight LLM state is lost — see §13.11 for the recovery / handoff path. |

### Why this exact split

- **Main is short, fast, voice-bound.** It can never afford to be staring at a half-parsed PDF when the user wants to ask a follow-up. So heavy work goes elsewhere.
- **Sub-agents are deep, slow, tool-bound.** They are allowed to be wordy in their own context. Main never sees that wordiness — only the report.
- **Both can search and recall** because those are *cheap and stateless*. Forcing every memory recall through a sub-agent would add 1–2 seconds of latency to "what's my address?".
- **Only one role can speak.** This is the difference between an assistant that feels like one person and an assistant where three voices fight for the mic.

### The directive grammar (what Main writes; what Supervisor parses)

```
[DELEGATE  capability=<name>  goal="<sentence>"  payload=<json>]
[STOP_TASK task_id=<uuid>]
[REMEMBER  key=<dotted.key>  value=<json>  source="user_intent"]
[RECALL    key=<dotted.key>]
[RECALL    chain key=<dotted.key>]
[RECALL    doc:<doc_id>]
[ANSWER_TO task_id=<uuid> answer=<json|string> mode="reply|amendment"]
[RESPOND_VIA chat|voice|both]
```

These are the **only** directives Main can emit. Anything else is plain text → goes to TTS / chat. The orchestrator's parser is small (≈ 120 lines of regex + Pydantic validation) and lives in `server/orchestrator/directives.py`.

`ANSWER_TO` is only for task coordination. It resumes a paused sub-agent or appends extra context to a running sub-agent. `RESPOND_VIA` overrides the computed default for the current turn only. Do not overload one directive for both meanings.

### `respond_via` full decision table (Rule 13)

The Supervisor computes `respond_via` at the start of every `handle_turn` call. It reads the most recent `client_state` (updated by the client on every change). The Main LLM may override with an explicit `[RESPOND_VIA ...]` directive, which takes final precedence.

| Input kind | Client conditions | `respond_via` | `interrupt_policy` |
|---|---|---|---|
| voice | any | `voice_and_chat` | `replace` |
| chat (typed) | `capabilities.tts = false` (declared in `hello`) | `chat_only` | `queue` |
| chat (typed) | `client_state.playback = playing` | `chat_only` | `queue` |
| chat (typed) | `client_state.route = none` (muted/no speaker) | `chat_only` | `queue` |
| chat (typed) | meeting mode active | `chat_only` | `queue` |
| chat (typed) | `client_state.visible = false` (app backgrounded) | `chat_only` | `queue` |
| chat (typed) | none of the above | **`voice_and_chat`** | `queue` |
| proactive (notifier) | `client_state.visible = false` | `chat_only` (push via Server 1 if available) | `queue` |
| proactive (notifier) | `client_state.capture = recording` | `chat_only` | `queue` |
| proactive (notifier) | meeting mode active | `chat_only` | `queue` |
| proactive (notifier) | NEEDS_INFO signal, any state | `voice_and_chat` | `queue` |
| proactive (notifier) | DONE signal, all conditions normal | `voice_and_chat` | `queue` |
| system (token expiring, reconnect) | any | `chat_only` | `queue` |

**Key clarifications:**

- `interrupt_policy=replace` means: if Main is currently speaking, the new voice turn cancels it immediately and starts fresh. Used for voice commands only.
- `interrupt_policy=queue` means: if Main is currently speaking, the new response is queued to play after current speech ends. Used for typed chat and proactive notifications.
- **A typed chat message NEVER interrupts ongoing speech.** The user chose to type; they can wait. If they want to interrupt, they use the wake word or interrupt button — which sends an explicit `interrupt` message, not a `chat` message.
- **`[RESPOND_VIA]` from Main overrides the computed value.** Main may emit `[RESPOND_VIA chat]` to suppress voice for a particular turn (e.g., the response contains code or a long table that doesn't read well aloud). Main may emit `[RESPOND_VIA voice]` for a turn that would otherwise be `chat_only` (e.g., an urgent proactive notification).

### Interrupt behavior — complete FSM

The interrupt FSM owns the speaking state machine and lives in `server/voice/interrupt.py`.

```
States: IDLE → THINKING → SPEAKING → QUEUED
                                   ↗
                         THINKING →
```

| Event | From state | Action | To state |
|---|---|---|---|
| `handle_turn` called | IDLE | Context assembly + submit to engine P0 | THINKING |
| First LLM token arrives | THINKING | Emit `caption{partial:true}`, start TTS for first sentence | SPEAKING |
| All LLM tokens done + all audio sent | SPEAKING | Emit `audio_end`, emit `chat_message{final:true}`, send `client_control{start_capture}` | IDLE |
| `interrupt` received from client | THINKING | Cancel P0 engine slot, discard directive buffer | IDLE |
| `interrupt` received from client | SPEAKING | Cancel P0 engine slot, discard remaining TTS queue, emit `audio_end{interrupted:true}`, emit `chat_message{final:false}` for text so far, send `client_control{clear_queue}`, send `client_control{start_capture}` | IDLE |
| New `handle_turn` arrives with `interrupt_policy=replace` | SPEAKING | Same as interrupt — cancel everything, start new turn | THINKING |
| New `handle_turn` arrives with `interrupt_policy=queue` | SPEAKING | Enqueue the new turn; current speech continues; queue depth = 1 | SPEAKING (queued turn waiting) |
| New `handle_turn` arrives with `interrupt_policy=queue` | SPEAKING (already 1 queued) | Replace the pending queued turn with the new one; current speech continues | SPEAKING (new queued turn waiting) |
| Current speech ends | SPEAKING (with queued turn) | Start the queued turn immediately | THINKING |
| `interrupt` received | SPEAKING (with queued turn) | Cancel current speech AND discard queued turn | IDLE |

**Echo suppression on every state transition into SPEAKING:**

Before the first `audio_start` frame of any TTS response:
1. `client_control{command:'stop_capture', reason:'tts_start', turn_id}` is sent.
2. The client mutes/stops capture immediately.
3. Binary PCM frames begin.
4. After `audio_end`, a timer fires after `SELF_ECHO_SUPPRESSION_DELAY` (default 1200 ms).
5. `client_control{command:'start_capture', reason:'echo_clear'}` is sent.
6. The client resumes capture.

This happens for **every** TTS output — voice-initiated, typed-chat-initiated, and proactive-notification-initiated. No exceptions. If the client declares `capabilities.aec=true` (hardware AEC on device), the delay in step 4 may be reduced to 300 ms, but the `stop_capture` / `start_capture` cycle still runs.

---

## 7.6 Main coordinates many sub-agents — no mix-ups

**Question:** With several tasks in flight, does Main confuse which sub-agent said what?

**Answer:** No, if we keep one invariant: **every signal and every `task_board` row is keyed by `task_id` (UUID).** The Supervisor is the only writer of `task_board`. A sub-agent worker is constructed with exactly one `task_id` and never sees another task's prompts, tool results, or KV slot. Parallel tasks use different engine slots; slot assignment is tracked in the pool, not in the LLM's head.

| Mechanism | What it prevents |
|---|---|
| Stable `task_id` per spawn | Mixing summaries between tasks. |
| Sub-agent prompt includes only its `goal` + capability bundle | Cross-task context bleed. |
| `report()` must include `task_id` in the envelope | Wrong row updated on the bus. |
| Main's context gets **structured task_board**, not raw sub-agent transcripts | Main "knows" task A is done and task B is at step 3 as **fields**, not as ambiguous prose from three voices. |
| Sub-agents cannot message each other | Hidden state / race conditions. |

After **`report(DONE, …)`**, the canonical outcome for Main is: **`result_summary`** (short), **`artifact` refs** (file id / URL), optional **`facts_to_persist`**. The full sub-agent conversation stays in Postgres (audit) but is **not** injected into Main unless you explicitly add a future `[RECALL task:<id>]` for debugging.

---

## 7.7 Intermediate progress (STEP) — UI vs voice, and how it reaches the user

Sub-agents **never** open TTS or WebSocket text. For "I'm still working on the next part" you have **three** legitimate paths. All of them go **through the Supervisor**; none go sub-agent → user direct.

### Path A — Activity feed only (default, lowest noise)

1. Sub-agent emits `report(STEP, summary="…")`.
2. Supervisor updates `task_board[task_id].latest_step`.
3. Transport emits `event{ kind: "task_step", task_id, summary }`.
4. Client shows pills / timeline **without** calling Main.

User sees progress in the UI. Main says nothing unless asked.

### Path B — User asks ("what's the status?")

1. User speaks or types a status question.
2. `handle_turn` builds Main prompt **including the current task_board snapshot**.
3. Main paraphrases **from structured fields**, e.g. *"The research task is finished. I'm still generating your PDF."*
4. TTS / chat is Main only. Respond_via is computed per Rule 13 (voice if session is voice-capable).

This is the usual pattern for voice-heavy clients without a rich feed.

### Path C — Optional brief spoken digests (product policy)

When **no** user turn is active, a **digest policy** (importance threshold + min interval, e.g. 45 s) may trigger a **synthetic turn**: Notifier asks Main to say one short line. Main still **does not** see raw tool traces — only `latest_step` strings. Example: *"Quick update — your homework draft is done; I'm rendering the PDF now."*

**Rule:** STEP summaries should be **user-safe one-liners** (no stack traces, no API keys). The sub-agent prompt should say so.

### Example phrases (all spoken by Main, not by sub-agents)

- *"That part's done — I'm still working on the PDF."*
- *"Two things are running: the search finished; the document is still building."*
- *"Task A is complete. Task B hit a blocker — I'll explain."* (then NEEDS_INFO handling)

---

## 7.8 PDF / homework-style chain (multi-tool inside one sub-agent)

One user goal can require many tools **inside a single** `[DELEGATE …]` (answer questions → assemble doc → `render_pdf` → upload). The Main Agent does not need one directive per tool.

**Happy path:** Sub-agent runs the chain, emits occasional `report(STEP, …)` for Path A/B/C above, then `report(DONE, summary="PDF ready", payload={ artifacts: [{kind:"pdf", …}] })`.

**User-facing completion:** Either Main handles the next user turn with the DONE already on the board, or the Notifier fires a synthetic turn. Main says something like *"Here's your homework PDF"* and a **`deliver_file`** / **`notify_download`** tool (or Server 1 helper) sends the bytes or signed URL — same pattern as §13.

**Production shortcut:** Register one fat tool `homework_to_pdf(...)` that wraps the chain. The orchestration **outside** the LLM is unchanged; only the tool implementation collapses steps.

---

## 7.9 Unified task coordination contract (`NEEDS_INFO`, amendments, notes)

Yes: the architecture already supports the five cases where a sub-agent asks a question, receives extra context mid-task, asks for confirmation, or suggests follow-up work. The reusable pattern is:

```
SubAgentWorker -> report(...) -> SignalBus -> Supervisor -> task_board -> Main -> user
user reply -> Main -> [ANSWER_TO task_id=...] -> Supervisor -> SubAgentWorker.resume_with(...)
```

This plan uses `llama-server`, not LiteRT. While the worker is alive, the engine slot may keep KV cache warm. The correctness guarantee does **not** depend on KV staying alive: `SubAgentWorker` also keeps an append-only message transcript in memory and checkpoints it to Postgres. If the slot is evicted or the process restarts, the worker resumes by replaying the task prompt + transcript to the same logical pause point.

### Canonical function names

These names are the target API. Step files may implement them incrementally, but do not invent parallel names.

| File | Function / class | Responsibility |
|---|---|---|
| `server/orchestrator/supervisor.py` | `Supervisor.handle_turn(input: TurnInput) -> None` | One entry point for voice, chat, proactive synthetic turns, and reconnect-visible pending tasks. |
| `server/orchestrator/supervisor.py` | `spawn_subagent(capability, goal, payload) -> task_id` | Creates the task row, creates worker state, assigns dependency/blocking state, emits `tool_started`. |
| `server/orchestrator/supervisor.py` | `apply_answer_to_task(task_id, answer, mode)` | Handles `[ANSWER_TO ...]`; resumes a paused task or appends context to a running task. |
| `server/orchestrator/task_board.py` | `TaskBoard.upsert_from_signal(signal)` | Canonical task status update: running, paused, blocked, waiting_user, done, error, cancelled. |
| `server/orchestrator/task_board.py` | `TaskBoard.render_for_main()` | Structured active-tasks block injected into every Main prompt. |
| `server/orchestrator/signal_bus.py` | `SignalBus.publish(signal)` / `drain(session_id)` | The only sub-agent -> supervisor channel. Persists every signal to PG for audit. |
| `server/subagents/worker.py` | `SubAgentWorker.run()` | Owns one task conversation. Calls tools through `ToolRunner`, emits `report()`, never touches transport. |
| `server/subagents/worker.py` | `SubAgentWorker.resume_with(message)` | Injects user/Main-provided answer or amendment as the next user message in the sub-agent transcript. |
| `server/subagents/worker.py` | `SubAgentWorker.pause(question, payload)` | Sets task state to paused/waiting_user after `report(NEEDS_INFO, ...)`. |
| `server/subagents/report.py` | `report(kind, summary, payload=None)` | The only output function visible to sub-agent prompts. Pydantic-validated before it reaches the bus. |
| `server/tools/registry.py` | `ToolRegistry.register(entry)` | Adds native or MCP-mirrored tools. Enforces unique names and schemas. |
| `server/tools/registry.py` | `ToolRegistry.resolve_for_capability(capability, user_id)` | Returns the exact tool slice injected into a sub-agent prompt. |
| `server/tools/registry.py` | `ToolRegistry.search(query, capability, user_id)` | Lets agents discover whether a tool exists without loading the full registry into the prompt. |
| `server/tools/runner.py` | `ToolRunner.execute(task_id, tool_call)` | Validates args, checks capability access, runs the function, normalizes result, injects it back to the worker. |

### `report()` signal schema

```python
class ReportSignal(BaseModel):
    task_id: str
    kind: Literal["STEP", "NEEDS_INFO", "DONE", "ERROR"]
    summary: str                         # user-safe, <= 80 tokens
    payload: dict[str, Any] = {}
    importance: float = 0.5               # NEEDS_INFO defaults to 1.0
    created_at: datetime
```

Rules:

- `STEP` updates UI/activity feed only by default. No Main call unless the user asks or digest policy fires.
- `NEEDS_INFO` pauses the task. `payload.question` is stored on `task_board[task_id].waiting_for`. Notifier fires proactive turn using Rule 13 to decide voice vs chat.
- `DONE` finalizes the task. Optional `payload.artifacts`, `payload.facts_to_persist`, `payload.note_for_agent`, and `payload.suggestion` are visible to Main as structured fields.
- `ERROR` is a failed task. If `payload.user_actionable=true`, Main surfaces it like `NEEDS_INFO`; otherwise Supervisor may auto-retry within the worker retry budget.

### Active tasks block shape

Main gets this structured block on every turn. It does not get raw sub-agent transcripts.

```json
{
  "active_tasks": [
    {
      "task_id": "x1",
      "capability": "research",
      "goal": "Research AI chips",
      "status": "paused",
      "latest_step": "collected sources",
      "waiting_for": "Should I focus on 2024-2025 chips or all-time history?",
      "result_summary": null,
      "allowed_actions": ["answer", "cancel"]
    }
  ],
  "recent_completed": [
    {
      "task_id": "r1",
      "status": "done",
      "result_summary": "Found 3 relevant emails about invoice #4421",
      "note_for_agent": "John also mentioned invoice #4422 is still unpaid",
      "suggestion": null
    }
  ]
}
```

### The five reusable cases

| Case | Sub-agent output | Supervisor state | Main action | Resume behavior |
|---|---|---|---|---|
| Needs more info | `report(NEEDS_INFO, summary, payload={"question": "..."})` | `task.status="paused"`, `waiting_for=question` | Asks user naturally via voice+chat (Rule 13) | `[ANSWER_TO task_id=x1 answer="..." mode="reply"]` calls `resume_with(...)`. |
| User adds context while running | No sub-agent signal required | Task remains `running`; task_board shows it | Main sees active task + new user text | `[ANSWER_TO task_id=x1 answer="Additional context: ..." mode="amendment"]` appends next message to worker queue. |
| Tool confirmation | Tool returns `ToolResult(status="confirmation_required", ...)`; worker converts to `NEEDS_INFO` | Task paused | Main asks for yes/no with details via voice+chat | User yes -> `[ANSWER_TO ... answer={"confirmed": true}]`; worker calls same tool with `confirmed=True`. |
| Note from finished task | `report(DONE, payload={"note_for_agent": "..."})` | Task done; note stored | Main decides whether to surface | If user wants it, Main delegates a new task. |
| Proactive suggestion | `report(DONE, payload={"suggestion": "..."})` | Task done; suggestion stored | Main may ask user if useful | If user says yes, Main delegates a new task. |

Sub-agent prompts should use clear prefixes only as a prompt convention (`NOTE_FOR_AGENT:`, `SUGGESTION:`), but code should store them in `payload.note_for_agent` and `payload.suggestion` when possible. Main is allowed to ignore suggestions when the user is busy, interrupted, or the suggestion is low value.

---

## 7.10 Tool access, discovery, return values, and confirmation

Tool access is intentionally asymmetric.

| Actor | What it sees | What it can call | Why |
|---|---|---|---|
| Main Agent | Directives, active task board, **native OpenAI-style tool_calls** (`web_search`, `memory_save`, `memory_recall`) via `complete_chat`, plus capability labels | Fast, stateless tools only; delegates everything heavy | Keeps voice latency low. Main prompt is a single `prompts/main.txt`; session context (date, warm profile, task board) is injected separately (see §7.10.1). |
| Sub-agent | Its capability prompt, its task goal/payload, `report()`, and only its allowed tool cards | Tools mapped to its capability by `ToolRegistry.resolve_for_capability(...)` | Keeps prompts small and prevents cross-domain tool misuse. |
| Tool runner code | Full registry, auth broker, schemas, confirmation policy, audit logger | Can execute any registered tool after capability + auth validation | Code enforces safety; LLM only requests. |

### `ToolEntry` schema

```python
class ToolEntry(BaseModel):
    name: str                              # "gmail.draft_create"
    capability: Literal["main", "research", "productivity", "comms", "data"]
    description: str                       # <= 80 tokens, prompt-visible
    args_schema: dict                      # JSON Schema
    result_schema: dict | None = None
    fn: Callable[..., Awaitable[ToolResult]]
    requires_auth: bool = False
    requires_confirmation: bool = False
    risk: Literal["read", "write", "send", "delete", "purchase"] = "read"
    cost_hint: Literal["cheap", "net", "heavy"] = "cheap"
    timeout_s: int = 30
```

### `ToolResult` schema

Every tool returns one normalized result. The LLM sees a compact text rendering of this model; code stores the full JSON.

```python
class ToolResult(BaseModel):
    status: Literal[
        "ok",
        "confirmation_required",
        "user_action_required",
        "not_capable",
        "error",
    ]
    summary: str
    data: dict[str, Any] = {}
    confirmation: dict[str, Any] | None = None
    safe_to_show_user: bool = True
    retryable: bool = False
```

Return-value rules:

- `ok`: inject into the worker as tool output.
- `confirmation_required`: worker must call `report(NEEDS_INFO, ...)` before the action is run. The follow-up tool call must include `confirmed=True` and the confirmation id/hash.
- `user_action_required`: worker must call `report(NEEDS_INFO, ...)`; examples: OAuth reconnect, missing file permission, payment login.
- `not_capable`: worker reports `DONE` or `ERROR` with a clear limitation. Main tells the user what is unsupported.
- `error`: runner retries if retryable and budget remains; otherwise worker emits `report(ERROR, ...)`.

### Tool discovery without huge prompts

Agents do not need the full registry in the system prompt. They get a small `tool_search` utility:

```python
tool_search(query: str, capability: str | None = None) -> list[ToolCard]
```

`ToolCard` contains only `name`, `capability`, `description`, `risk`, and required auth labels. Main calls **`web_search` / `memory_*` as native function tools** (llama-server `/v1/chat/completions`). `[DELEGATE capability=main …]` remains a **fallback** parser path for the same tools when the model emits directive text instead of `tool_calls`. Sub-agents use capability bundles. The runner still validates every final tool call against `ToolRegistry`.

### 7.10.1 Main turn pipeline (post-Step-10 — implemented)

This amends Step 7’s original “DELEGATE-only main tools” design. **No user-message keyword routing** — the model + prompt decide when to search.

**Prompt assembly (`server/engine/prompt.py`):**
- `system` = static `prompts/main.txt` only.
- Separate labeled user turn for session context: **today’s date**, warm profile, compressed summary, task board, injected tool/recall blocks.
- Real user message is always the last user turn.
- `build_main_chat_messages()` is the canonical format for `complete_chat`.

**Turn flow (`server/orchestrator/supervisor.py`):**
1. **Pass 1:** `engine_pool.complete_chat()` with `tools=openai_tools_for_main()` (`web_search`, `memory_save`, `memory_recall`).
2. If `tool_calls` → `run_native_tool_calls()` → `_answer_after_web_search()` (prefer `speak_web_search_results()` from Tavily/DDG snippets; no streaming LLM follow-up for web_search-only turns).
3. Else parse `[DELEGATE]` / `[REMEMBER]` / `[RECALL]` from prose; **`[DELEGATE capability=main]`** still runs via `tool_dispatch` when the model uses directive syntax.
4. **Safety nets (`tool_fallback.py`, model output only):** if the model acks without tools, leaks `[web_search …]`, cites ungrounded prices, or past calendar years → run `web_search` and speak snippets; never trust hallucinated live data.
5. **Delivery:** `tool_status_while_searching()` speaks a short safe line while search runs (not stale facts). `revoice_final` re-speaks the grounded answer if streaming TTS already played bad partials.

**Typed chat while TTS is playing (`chat_queue.py`):**
- Queue depth 1; background `run_turn` while playback active; deliver when idle (+ 3s post-TTS grace in `session_busy.py`).
- Trivial follow-ups (`?`, `!`) do not replace a queued message.

**Not used:** split prompts (`main_core` / `main_tools`), intent regex routing, search-before-LLM keyword paths.

### Confirmation example: email send

The comms tool never sends just because the LLM asked. It returns a confirmation result first:

```json
{
  "status": "confirmation_required",
  "summary": "Send email to sarah@co.com?",
  "confirmation": {
    "id": "confirm_abc",
    "action": "gmail.send",
    "preview": {
      "to": "sarah@co.com",
      "subject": "Meeting confirmation",
      "body": "Hi Sarah, confirming our meeting on Thursday at 2pm."
    }
  }
}
```

The sub-agent prompt rule is fixed: if any tool result has `status="confirmation_required"`, call `report(NEEDS_INFO, summary="...", payload={confirmation})`. After the user says yes, Main emits:

```
[ANSWER_TO task_id=x1 answer={"confirmed":true,"confirmation_id":"confirm_abc"} mode="reply"]
```

The worker resumes and calls:

```python
gmail.send(..., confirmed=True, confirmation_id="confirm_abc")
```

`ToolRunner` verifies the confirmation id still matches the original action preview before executing. This prevents prompt injection from turning "yes" into a different send/delete/purchase action.

---

## 7.11 Full implementation API map by plane

This is the broad function catalog. It is not saying every function ships in Step 1. It is the naming map so future steps do not invent duplicate concepts. Step files can mark a function as stubbed until its phase.

### Auth and session

| File | Function / class | Responsibility |
|---|---|---|
| `server/auth.py` | `verify_token(token) -> TokenPayload` | Decode RS256 JWT, validate claims, check Server 1 Redis blocklist. |
| `server/auth.py` | `get_server1_oauth_token(user_id, provider, scopes) -> OAuthToken or AuthActionRequired` | Tool-runner helper for Gmail/Calendar/Drive/Notion credentials owned by Server 1. |
| `server/memory/session.py` | `load_or_create_session(user_id, session_id, client_meta) -> SessionState` | Rehydrate server-side session on connect/reconnect. |
| `server/memory/session.py` | `persist_session_snapshot(session_state)` | Save state needed for reconnect/device handoff. |
| `server/orchestrator/supervisor.py` | `Supervisor.attach_transport(transport)` / `detach_transport(reason)` | Rebind a live or reconnected client to the same logical session. |

### Transport, protocol, upload, and client control

| File | Function / class | Responsibility |
|---|---|---|
| `server/transport/ws.py` | `ws_endpoint(websocket)` | FastAPI WebSocket entry point. Authenticates, enforces session singleton (§5.0), accepts, creates/attaches Supervisor. |
| `server/transport/ws.py` | `inbound_loop()` / `outbound_loop()` | Split receive/send loops inside one TaskGroup. |
| `server/transport/ws.py` | `enforce_session_singleton(user_id, new_ws) -> Supervisor` | Finds existing Supervisor for user_id if any; closes old WS with `session_superseded`; reattaches or creates. |
| `server/transport/protocol.py` | `parse_client_message(raw) -> ClientMessage` | Pydantic discriminated-union parse for JSON frames. |
| `server/transport/protocol.py` | `serialize_server_message(message) -> str` | Typed server JSON frame serialization. |
| `server/transport/ws.py` | `send_json(message)` / `send_audio_frame(pcm)` | The only low-level WebSocket send functions. |
| `server/transport/ws.py` | `receive_audio_frame(bytes)` | Routes binary PCM to Supervisor/voice pipeline. |
| `server/transport/uploads.py` | `upload_file(request, token) -> UploadedFile` | Validates JWT, MIME, size, checksum; stores bytes; returns `file_id`. |
| `server/transport/uploads.py` | `get_uploaded_file(file_id, user_id) -> FileRef` | Retrieves metadata/path for tools and sub-agents. |
| `server/transport/uploads.py` | `delete_uploaded_file(file_id, user_id)` | User-initiated cleanup / retention policy hook. |
| `server/transport/client_control.py` | `send_client_control(command, reason, turn_id=None)` | Server asks client to play/pause/stop/duck/unduck/start/stop capture. |
| `server/transport/client_control.py` | `handle_client_state(state)` | Client confirms local playback/capture/visibility/audio route. Updates the respond_via cache for this session. |
| `server/transport/session_busy.py` | `chat_should_queue(session)` / `playback_blocks_voice(session)` | Queue typed chat during TTS + 3s post-playback grace (§7.10.1). |
| `server/transport/chat_queue.py` | `start_background_chat_compute(...)` / `try_deliver_pending_chat(...)` | Depth-1 queue; compute turn during playback; deliver when idle. |
| `server/transport/turn_coordinator.py` | `run_supervisor_text_turn(...)` / `revoice_final` | Shared chat/proactive delivery; re-speak grounded answer after bad streaming partials. |

Client-control rule: the server may request local audio behavior, but the client is the device owner. The server sends `client_control`; the client replies with `client_state`. If the client cannot comply, it reports state honestly and the Supervisor adapts. The server never assumes compliance — it always reads `client_state` to know actual device status.

### Voice, audio, and interrupt

| File | Function / class | Responsibility |
|---|---|---|
| `server/voice/stt/base.py` | `STTBackend.transcribe_stream(chunks) -> AsyncIterator[TranscriptEvent]` | Common STT interface for Groq/local. |
| `server/voice/stt/groq.py` | `GroqWhisper.transcribe_stream(...)` | Primary low-latency network STT. |
| `server/voice/stt/local.py` | `LocalFasterWhisper.transcribe(...)` | Offline fallback for completed utterances. |
| `server/voice/tts/kokoro.py` | `KokoroTTS.synthesize_stream(text, voice) -> AsyncIterator[PcmFrame]` | Sentence-level streaming TTS. |
| `server/voice/vad/silero.py` | `SileroVAD.accept_frame(frame) -> VadEvent` | Server-side end-of-utterance fallback and tests. |
| `server/voice/interrupt.py` | `InterruptController.handle_interrupt(source)` | Single interrupt entry point. Cancels speech scope, clears directive buffer, discards TTS queue, returns to IDLE. |
| `server/voice/interrupt.py` | `cancel_tts(turn_id)` / `cancel_main_decode(turn_id)` | Stop user-facing speech/Main only. Sub-agents continue unless `[STOP_TASK]`. |
| `server/voice/interrupt.py` | `drop_partial_utterance(reason)` | Discards incomplete STT text after wake/button interrupt. |
| `server/voice/interrupt.py` | `compute_respond_via(session_state, input_kind) -> RespondVia` | Implements the full decision table from §7.5 Rule 13. Called at the start of every handle_turn. |
| `server/voice/interrupt.py` | `begin_tts_with_echo_suppression(turn_id)` | Sends `stop_capture` before first audio frame; schedules `start_capture` after audio_end + delay. |
| `server/orchestrator/supervisor.py` | `on_audio_start(payload)` / `on_audio_chunk(bytes)` / `on_audio_end()` | Bridges transport audio events into STT/turn handling. |

### Orchestrator, turns, directives, and tasks

| File | Function / class | Responsibility |
|---|---|---|
| `server/orchestrator/supervisor.py` | `handle_turn(input: TurnInput)` | One entry point for chat, voice transcript, proactive signal, and file/image turns. Computes respond_via at start. |
| `server/orchestrator/supervisor.py` | `run_turn(...)` | Main turn: `complete_chat` + native `tool_calls` + safety nets (§7.10.1). Replaces streaming-only main path for typed chat. |
| `server/orchestrator/supervisor.py` | `assemble_main_context(input) -> MainContext` | Warm profile, history, active tasks, retrieval snippets, attachment summaries. |
| `server/orchestrator/tool_dispatch.py` | `run_native_tool_calls(...)` / `speak_web_search_results(runs)` | Execute OpenAI-style tool_calls; speak grounded answers from search snippets. |
| `server/orchestrator/tool_fallback.py` | `should_fallback_web_search(model_content=...)` / `tool_status_while_searching()` | Model-output safety nets; safe status line while search runs. |
| `server/orchestrator/prose.py` | `sanitize_spoken_prose(text)` | Strip markdown, URLs, `[web_search]` leaks from TTS/caption text. |
| `server/orchestrator/directives.py` | `parse_directive_blocks(stream) -> AsyncIterator[Directive | TextChunk]` | Splits plain text from directive blocks safely while streaming. |
| `server/orchestrator/directives.py` | `validate_directive(directive) -> TypedDirective` | Pydantic validation for DELEGATE/STOP_TASK/ANSWER_TO/etc. |
| `server/orchestrator/supervisor.py` | `execute_directive(directive)` | Applies parsed directives to memory, tasks, retrieval, response channel, or tool dispatch. |
| `server/orchestrator/task_board.py` | `create_task(...)`, `pause_task(...)`, `resume_task(...)`, `cancel_task(...)`, `complete_task(...)` | Canonical task lifecycle mutations. |
| `server/orchestrator/task_board.py` | `render_for_main()` / `render_for_client()` | Separate compact Main context from richer client activity feed. |
| `server/orchestrator/notifier.py` | `maybe_surface_signal(signal)` | Gates DONE/NEEDS_INFO/ERROR by user silence, importance, debounce, client visibility, and session mode. |
| `server/orchestrator/notifier.py` | `build_synthetic_turn(signals)` | Runs Main through normal `handle_turn` for proactive text. Uses Rule 13 to determine respond_via. |

### Sub-agents and capability bundles

| File | Function / class | Responsibility |
|---|---|---|
| `server/subagents/worker.py` | `SubAgentWorker.run()` | Main task loop: model step -> tool call/report -> inject result -> continue. |
| `server/subagents/worker.py` | `resume_with(message)` | Injects answer/amendment from `[ANSWER_TO]`. |
| `server/subagents/worker.py` | `checkpoint()` / `restore(task_id)` | Saves/restores transcript and tool state for reconnect/restart. |
| `server/subagents/report.py` | `parse_report(text) -> ReportSignal` | Validates `report(...)` output from the sub-agent. |
| `server/subagents/capabilities/*/manifest.py` | `load_capability(name) -> CapabilityBundle` | Prompt path, allowed tools, budgets, confirmation instructions. |
| `server/subagents/capabilities/*/manifest.py` | `render_tool_cards(tools) -> str` | Compact per-capability tool descriptions injected into worker prompt. |

### Engine and prompt

| File | Function / class | Responsibility |
|---|---|---|
| `server/engine/runner.py` | `start_llama_server()` / `stop_llama_server()` / `health_check()` | Owns the single llama-server subprocess. |
| `server/engine/pool.py` | `submit(request, priority, slot_hint=None) -> CompletionHandle` | Queue model work by P0/P1/P2 (streaming sub-agents, legacy paths). |
| `server/engine/pool.py` | `complete_chat(messages, tools=...) -> ChatCompletionResult` | Non-streaming chat completion with native `tool_calls` (main turn §7.10.1). |
| `server/engine/pool.py` | `cancel(handle)` | Cancel Main decode on interrupt; task cancellation uses worker-level cancel. |
| `server/engine/pool.py` | `reserve_slot(role, task_id)` / `release_slot(slot_id)` | Slot accounting for Main/sub-agent/summarizer. |
| `server/engine/prompt.py` | `build_main_chat_messages(context)` | Canonical main messages: static system + session context user turn + user message (§7.10.1). |
| `server/engine/prompt.py` | `today_context_line()` | Injects today's date into session context every turn. |
| `server/engine/prompt.py` | `build_main_prompt(context)` / `build_subagent_prompt(bundle, task)` / `build_summarizer_prompt(...)` | Legacy string prompt + sub-agent/summarizer assembly. |

### Memory, retrieval, files, and summarization

| File | Function / class | Responsibility |
|---|---|---|
| `server/memory/facts.py` | `set_fact(key, value, source, confidence)` | Versioned write; old active row is superseded, never deleted. |
| `server/memory/facts.py` | `get_fact(key)` / `get_chain(key)` | Active fact and historical chain retrieval. |
| `server/memory/warm.py` | `build_warm_profile(user_id)` / `mark_dirty(user_id)` | Always-in-context profile cache. |
| `server/memory/retrieval.py` | `retrieve(query, filters, k) -> list[Snippet]` | LanceDB semantic retrieval with citations. |
| `server/memory/session.py` | `append_turn(turn)` / `recent_turns(limit)` / `compressed_history()` | Raw and summarized conversation history. |
| `server/memory/summarizer.py` | `summarize_session(session_id)` | Compresses old turns after response. |
| `server/memory/summarizer.py` | `extract_facts_from_task(task_id)` | Converts `facts_to_persist` / stable discoveries into versioned facts. |
| `server/memory/files.py` | `summarize_attachment(file_id)` | OCR/image caption/doc preview used in Main context. Heavy work delegates to sub-agent. |

### Tool system and MCP

| File | Function / class | Responsibility |
|---|---|---|
| `server/tools/registry.py` | `register(entry)` / `get(name)` / `resolve_for_capability(...)` / `search(...)` | Central tool catalog. |
| `server/tools/runner.py` | `execute(task_id, tool_call) -> ToolResult` | Args validation, capability gate, auth gate, timeout, audit, normalized result. |
| `server/tools/runner.py` | `require_confirmation(tool_call, preview) -> ToolResult` | Returns `confirmation_required` with stable confirmation id/hash. |
| `server/tools/runner.py` | `verify_confirmation(confirmation_id, tool_call)` | Prevents "yes" from approving a changed action. |
| `server/tools/mcp_adapter.py` | `load_mcp_servers(config)` / `mirror_tools()` / `handle_tools_changed()` | Converts MCP tools into `ToolEntry` rows. |
| `server/tools/tool_search.py` | `tool_search(query, capability=None) -> list[ToolCard]` | Compact discovery tool for Main/sub-agent prompts. |

### Client reference app

| File | Function / class | Responsibility |
|---|---|---|
| `web-client/client.js` | `connect(token)` / `sendJson(type, payload)` / `sendPcmFrame(frame)` | Basic WebSocket contract implementation. |
| `web-client/client.js` | `startMic()` / `stopMic()` / `recordOneSecond()` | AudioWorklet capture and PCM conversion. |
| `web-client/client.js` | `handleServerAudio(frame)` / `handleClientControl(command)` | Playback queue and server-requested local controls. `stop_capture` mutes mic. `start_capture` resumes after echo suppression delay. `clear_queue` discards all buffered audio immediately. |
| `web-client/client.js` | `uploadFile(file) -> UploadedFile` / `sendChat(text, attachments)` | User file/image upload, then chat reference. |
| `web-client/client.js` | `renderCaption(event)` / `renderChatMessage(event)` / `renderEvent(event)` | Live captions (sentence-by-sentence), final chat messages, and activity feed pills. |
| `web-client/client.js` | `handleClientState(state)` | Sends `client_state` update to server whenever local audio/visibility changes. |

---

## 8. Phase plan (the order in which we build)

Each phase is one or more `doc/step-NN.md` files. Status here is the source of truth.

### Phase 1 — Spine (in progress)

The minimum that proves the architecture is real. End of phase 1 you can talk to Vayumi from the web client, it understands you, replies in voice, and uses one tool. No sub-agents yet.

| # | Step | File | Status |
|---|---|---|---|
| 1 | Project scaffold + config + db/redis/lancedb wiring + Server 1 JWT auth + WebSocket echo | `doc/step-01.md` | ✅ |
| 2 | Engine plane: `llama-server` runner + slot pool + main-only completion | `doc/step-02.md` | ✅ |
| 3 | Voice plane: Groq STT + Kokoro TTS + interrupt FSM | `doc/step-03.md` | ✅ |
| 4 | Web client v1 (single HTML file): mic, WS, captions, playback, interrupt button, client_state/client_control handling | `doc/step-04.md` | ✅ |
| 5 | Memory v1: warm profile + session history + Postgres versioned facts | `doc/step-05.md` | ✅ |
| 6 | v1.7 contract backfill: session singleton + respond_via + echo suppression + chat_message | `doc/step-06.md` | ✅ |
| 7 | Tool plane: registry + runner + `tool_search` + `web_search` (Tavily/DDG) + Main can call cheap tools | `doc/step-07.md` | ✅ |

### Phase 2 — Multi-agent

| # | Step | Status |
|---|---|---|
| 8 | Sub-agent worker + signal bus + `report()` schema + task pause/resume via `[ANSWER_TO task_id=...]` | ✅ |
| 9 | Capability bundles + per-capability prompts + 3 capabilities (research, productivity, comms) + tool access gates | ✅ |
| 10 | Proactive notifier + synthetic turn pipeline + respond_via decision per Rule 13 | ✅ |
| 11 | LanceDB retrieval tool + memory_recall on-demand | ✅ |
| 12 | Summarizer (P2) + automatic compression at 20k tokens | ✅ |

### Phase 3 — Modes & polish

| # | Step | Status |
|---|---|---|
| 13 | Meeting mode (diarization-friendly transcript accumulation, post-meeting summary) | ⬜ |
| 14 | Local STT fallback (faster-whisper) + offline mode flag | ⬜ |
| 15 | Server-side wake-word echo trap (anti-self-trigger when TTS is playing, extends Rule 12) | ⬜ |
| 16 | File/image upload + attachment summaries + long-input ack + chunked async doc analysis | ⬜ |
| 17 | MCP adapter — connect arbitrary MCP servers, mirror their tools | ⬜ |

### Phase 4 — Clients & deploy

| # | Step | Status |
|---|---|---|
| 18 | Mobile reference client (React Native or Flutter — your pick) | ⬜ |
| 19 | ESP32 firmware + protocol port | ⬜ |
| 20 | Production hardening: backpressure, reconnection, rate limits | ⬜ |
| 21 | Observability dashboard | ⬜ |

---

## 9. The "did we get unstuck" checks

Past restarts happened because of these specific traps. Each is now a hard rule.

| Trap | Hard rule |
|---|---|
| "Loaded the model multiple times" | The engine plane is the **only** place that talks to `llama-server`. There is exactly one runner. Sub-agents do not import the engine; they go through `pool.submit(...)`. |
| "Subagent context bled into main" | Subagents never write to the main session history. They `report()` to the signal bus. Only the supervisor decides what enters main's context. |
| "Memory got hallucinated" | Facts only get written via `memory_save` (typed args) or the post-turn summarizer (typed extraction schema). Never inferred from free text inside the main loop. |
| "Tool calling broke multi-step" | Main does **not** do raw OpenAI tool-calling. It writes `[DELEGATE capability=research goal="…"]` directives. The orchestrator parses, validates, spawns. Single-step tools (web_search, memory_save) are still directives, just shorter ones. This isolates Main from tool schemas entirely. |
| "Voice and chat fought over state" | Both go through `supervisor.handle_turn(input)`. There's one turn pipeline; voice and chat are just two different `input.kind` values. respond_via is computed from session state, not from a separate code path. |
| "The client integration broke at the end" | The web client is in the repo from step 1. Every step has an acceptance test that includes "the web client still works." If it doesn't, the step is not done. |
| "Async deadlocks during interrupts" | One asyncio event loop. Every long-running coroutine has a `cancel_scope`. Interrupt = cancel the speech scope only. Tasks live in their own scope. |
| "Stack got out of date" | This `PLAN.md` is the source of truth. If a library is replaced, we add a row to the changelog and update Section 2. We don't switch silently. |
| "Two devices connected at once" | Session singleton enforced at connection time. Old WS gets `session_superseded`, new WS gets `welcome{resumed:true}`. Sub-agents never notice — they're bound to the Supervisor, not the socket. |
| "Typed chat got no voice response" | respond_via is computed per Rule 13 in §7. Default for typed chat with voice-capable session is `voice_and_chat`. This is explicit code in `compute_respond_via()`, not an afterthought. |
| "AI's own voice triggered the wake word" | Rule 12 is mandatory: `stop_capture` before every TTS output, `start_capture` after echo suppression delay. No exceptions. `begin_tts_with_echo_suppression()` is the only function that sends `audio_start`. It always sends `stop_capture` first. |

---

## 10. Environment variables

Environment variables are for secrets, deployment-specific endpoints, machine-local paths, ports, and operator overrides. Ordinary non-secret defaults belong in `server/config.py` so local development does not require a large `.env` file.

```bash
# App
APP_ENV=dev                         # dev | prod
PORT=8080
LOG_LEVEL=info

# Server 1 handshake
JWT_PUBLIC_KEY=                     # RS256 PEM, same as Server 1's public key
SERVER1_REDIS_URL=                  # for blocklist lookups (jti)

# Database
DATABASE_URL=                       # postgres connection string (Supabase or self-host)
LANCEDB_DIR=./data/lancedb

# Redis (own + shared signal bus)
REDIS_URL=

# Uploads
UPLOAD_DIR=./data/uploads
UPLOAD_MAX_IMAGE_MB=20
UPLOAD_MAX_DOC_MB=100

# LLM
LLAMA_SERVER_BIN=./bin/llama-server
LLAMA_MODEL_PATH=./models/gemma-3n-e2b-it-q4_k_m.gguf
LLAMA_PORT=8081
LLAMA_PARALLEL_SLOTS=4
LLAMA_CTX_PER_SLOT=8192             # 4 slots × 8k = 32k total kv

# STT
STT_BACKEND=groq                    # groq | local
GROQ_API_KEY=
STT_LOCAL_MODEL=base.en             # faster-whisper

# TTS
KOKORO_MODEL_DIR=./models/tts
KOKORO_VOICE=af_heart

# Voice
SELF_ECHO_SUPPRESSION_DELAY_MS=1200  # how long after audio_end to wait before start_capture
AEC_CLIENT_SUPPRESSION_DELAY_MS=300  # shorter delay when client declares capabilities.aec=true

# Embeddings
BGE_MODEL_PATH=./models/bge-small-en-v1.5.onnx

# Tools
TAVILY_API_KEY=                     # optional; falls back to DDG
MCP_SERVERS_JSON=./config/mcp.json  # optional; declares MCP servers to mirror

# Session
SESSION_SINGLETON_CLOSE_CODE=4001   # WebSocket close code sent on session_superseded
SESSION_LINGER_SECONDS=60           # how long Supervisor stays alive after WS disconnect before persisting and releasing
```

---

## 11. Initial dependencies (Python 3.11)

```toml
# pyproject.toml — illustrative only, locked in step-01
[project]
dependencies = [
  "fastapi>=0.115",
  "uvicorn[standard]>=0.32",
  "pydantic>=2.9",
  "pydantic-settings>=2.6",
  "structlog>=24.4",
  "asyncpg>=0.30",
  "redis>=5.2",
  "lancedb>=0.15",
  "httpx>=0.28",
  "python-jose[cryptography]>=3.3",
  "numpy>=1.26",
  "soundfile>=0.12",
  "silero-vad>=5.1",
  "pykokoro>=0.6",
  "faster-whisper>=1.1",
  "groq>=0.13",
  "trafilatura>=1.12",
  "tavily-python>=0.5",
  "sentence-transformers>=3.3",     # only for the encoder; we ONNX-export at build
  "modelcontextprotocol>=1.0",
]

[tool.uv]
dev-dependencies = [
  "pytest>=8.3",
  "pytest-asyncio>=0.24",
  "pytest-recording>=0.13",
  "ruff>=0.7",
  "mypy>=1.13",
]
```

---

## 12. How to read the rest of `doc/`

- Find the current step in **Section 8** (first row with status ⬜). Read `doc/step-NN.md` for that step.
- Completed steps stay in `doc/step-NN.md` for reference; do not redo them (see `doc/history.md`).
- Each step file follows this skeleton:

  ```
  # Step NN — <one-line goal>

  Status: ⬜ pending | 🔄 in progress | ✅ done
  Depends on: step-(NN-1)

  ## Goal
  ## Files this step creates or changes
  ## Detailed tasks
  ## Acceptance test (the single command + expected output that proves done)
  ## Out of scope (explicitly NOT in this step)
  ## Risks and how we'll catch them
  ## Notes for the next step
  ```

---

## 13. Worked example — a real multi-step session, end to end

This section is the **acceptance test for understanding**. If you can follow every step and explain *why* each thing happens, you understand the system. It exercises: voice + typed chat (with voice response), two parallel sub-agents, a mid-task user interjection, a memory update with versioning, a `[RECALL]`, an interrupt that does NOT kill background tasks, a sub-agent `NEEDS_INFO`, a tool failure with recovery, the proactive notifier surfacing completions, and the session singleton handling a device handover.

The diagram companion is **page 15** of `orchestrator_diagram_v3.drawio` (one giant sequence chart of this same example).

### 13.0 Initial state

- User "Alex" (`user_id=u_42`) is connected on the **web client**, voice mode.
- Server 1 issued JWT 12 minutes ago; valid for another 3 minutes.
- Postgres `facts` already contains:
  ```
  ('name',              'Alex',                          active=true)
  ('city',              'Boston',                        active=true)
  ('email.work',        'alex@acme.com',                 active=true)
  ('comm_style.tone',   'concise',                       active=true)
  ```
- Warm profile is built and cached: 480 tokens.
- llama-server is up: slot 0 holds Main's KV (system prompt + last 6 turns ≈ 2.4k tokens). Slots 1, 2, 3 are free.
- Redis signal-bus channel is subscribed for this session.
- Conversation context already in Main: light banter from earlier today.
- Latest `client_state`: `{playback:'idle', capture:'idle', visible:true, route:'speaker'}`.

### 13.1 Turn 1 — User gives a multi-step goal (voice)

**User says:** *"Hey Vayumi — find three calendar-sharing apps that work on iOS and Android, compare pricing, and draft an email to my team recommending one."*

What happens, in order, with timestamps relative to when the user finished speaking:

| t (ms) | Component | Action |
|---|---|---|
| 0 | Client (web) | Local Silero VAD signals end-of-utterance. Sends `audio_end`. |
| ~250 | Voice plane | Groq Whisper streaming returns FINAL transcript. |
| 260 | Supervisor | `handle_turn(input={kind:'voice', text:'...'})`. `compute_respond_via(session_state, 'voice')` → `voice_and_chat`, `replace`. State `IDLE → THINKING`. |
| 265 | Memory plane | Concurrent fetch: warm profile (cached, free), recent history (8 turns from PG), task_board snapshot (empty), drain signal_bus (empty). |
| 320 | Engine pool | Build Main prompt: system + warm + history + user_msg ≈ 3.0k tokens. Submit P0 to slot 0. |
| 700 | Main (slot 0) | First token arrives. Begins streaming. |
| 720 | Directives parser | Reads first 30 tokens — plain text: *"Got it — I'll find apps and start a draft in parallel."* |
| 720 | Transport | `begin_tts_with_echo_suppression(turn_id)` called. Sends `client_control{stop_capture, reason:'tts_start'}`. Client mutes mic. |
| 725 | Transport | Emits `caption{text:"Got it — I'll find apps and start a draft in parallel.", partial:false, turn_id}`. |
| 800 | Voice plane | Kokoro emits first 20 ms PCM frame. Sends `audio_start{turn_id}`. |
| 850 | Transport | First audio frame leaves the WebSocket. **User hears the start of the reply at ~1.0 s.** State `THINKING → SPEAKING`. |
| 1100 | Main (still streaming) | Emits two directive blocks back-to-back (stripped from TTS/caption stream): |

```
[DELEGATE capability=research
   goal="find 3 calendar-sharing apps on iOS+Android, compare pricing"
   payload={"output_format":"comparison_table","constraints":["iOS","Android"]}]

[DELEGATE capability=productivity
   goal="draft a recommendation email to the work team"
   payload={"recipient_hint":"team@acme.com","tone":"concise","blocked_on":"r1_done"}]
```

| t (ms) | Component | Action |
|---|---|---|
| 1101 | Directives parser | Parses both. Validates. Second has `blocked_on:"r1_done"` — held with status `blocked`. |
| 1110 | Supervisor | `spawn_subagent(research, …)` → `task_id=r1`, slot 1, status `running`. |
| 1115 | Supervisor | Creates `task_id=p2`, status `blocked`. |
| 1120 | Transport | Emits `event{kind:'tool_started', task_id:'r1', …}` and `event` for p2 (queued). |
| 1200 | Main (slot 0) | Closing sentence: *"I'll let you know when the comparison is ready."* Emits `[RESPOND_VIA voice]`. Stops. |
| 1250 | Transport | Sends `audio_end{turn_id}`. Starts echo suppression timer (1200 ms). |
| 1300 | Transport | Emits `chat_message{text:"Got it — I'll find apps and start a draft in parallel. I'll let you know when the comparison is ready.", turn_id, final:true}`. |
| 2450 | Transport | Echo suppression timer fires. Sends `client_control{start_capture, reason:'echo_clear'}`. Client resumes mic. State `SPEAKING → IDLE`. |

**What the user sees / hears:** voice reply ≈ 1.0 s in, two activity-feed pills appear. Captions shown in sync with speech. Full chat message appears in the chat UI. Mic resumes after 1.2 s of silence post-speech.

### 13.2 Turn 2 — User TYPES a message (not voice)

While sub-agents are running, user types in the chat box: *"Actually, also check if any of them have a free tier."*

| t | Component | Action |
|---|---|---|
| 0 | Supervisor | `handle_turn(input={kind:'chat', text:'...'})`. |
| 1 | Voice plane | `compute_respond_via(session_state={playback:'idle', capture:'idle', visible:true, route:'speaker'}, 'chat')` — none of the blocking conditions apply → **`voice_and_chat`**, `interrupt_policy=queue`. |
| 50 | Memory | Concurrent: warm profile check (not dirty, cached), session state check. |
| 100 | Context | task_board includes r1 (running, STEP "picked 3 candidates") and p2 (blocked). |
| 400 | Main | Streams: *"Got it — I'll make sure to check free tiers too."* Emits `[ANSWER_TO task_id=r1 answer="Also check if any apps have a free tier" mode="amendment"]`. |
| 401 | Transport | `begin_tts_with_echo_suppression(turn_id_2)`. Sends `client_control{stop_capture}`. Emits `caption`. |
| 500 | Transport | Audio starts. `interrupt_policy=queue` — if Main was speaking (it's not), this would queue. Since IDLE, it plays immediately. |
| 600 | Supervisor | Applies `[ANSWER_TO]` — appends amendment to r1's input queue. r1 will process it on its next reasoning step. |
| 700 | Transport | `audio_end`. `chat_message{text:"Got it — I'll make sure to check free tiers too.", final:true}`. Echo suppression timer starts. |

**Key point:** The user typed, but they got a voice reply AND saw the text in the chat. This is `voice_and_chat` for typed input — exactly what Rule 11 specifies. The interrupt_policy was `queue` so if the AI had been mid-speech, the response would have waited.

### 13.3 Sub-agents r1 and p2 work; r1 finishes

(Same as original §13.2 sub-agent work. r1 finds Cron, Fantastical, Vimcal, checks free tiers, emits STEP signals that update the activity feed. r1 emits DONE. p2 unblocks.)

### 13.4 r2 hits a problem — `NEEDS_INFO` and proactive notification

p2 tries to send via gmail, gets OAuth scope error, emits `NEEDS_INFO`. Notifier fires.

`build_synthetic_turn(signals=[{task:p2, kind:NEEDS_INFO}])`:
- `input.kind = 'proactive'`
- `compute_respond_via` check: `client_state.visible=true`, `capture='idle'`, NEEDS_INFO importance=1.0, not meeting mode → **`voice_and_chat`**, `queue`.

Main streams: *"Quick blocker on the email draft — your gmail is connected as read-only. Want me to open the reconnect flow so I can draft on your behalf? Otherwise I can give you a copy-pasteable text right here."*

`begin_tts_with_echo_suppression()` runs. User hears and reads this proactively — without having said anything. This is the PersonaPlex-like push behavior.

### 13.5 Turn 3 — User responds, then interrupts mid-speech, then changes mind

User (voice): *"Just give me the text he—"* — changes mind mid-sentence. Says: *"Vayumi, stop. Forget the email — just tell me what Cron costs."*

| t | Component | Action |
|---|---|---|
| 0 | Client | Wake-word "Vayumi" fires. Sends `interrupt{source:'wake'}`. Begins capturing new utterance. |
| 5 ms | Supervisor | `InterruptController.handle_interrupt('wake')`. |
| 5 ms | Voice plane | State → IDLE. `cancel_tts(current_turn_id)`. Sends `audio_end{interrupted:true}`. Sends `client_control{clear_queue}`. Sends `client_control{start_capture}` immediately (interrupt overrides echo suppression delay — user needs to speak now). |
| 5 ms | Directives | Directive buffer cleared. |
| 5 ms | Background tasks | **Untouched.** p2 remains WAIT_USER. r1 is already done. |
| ~700 | Voice plane | STT FINAL: *"Just give me the text he"* — the aborted first utterance, dropped (interrupt before `audio_end`). |
| ~1200 | Voice plane | STT FINAL: *"forget the email — just tell me what Cron costs."* |
| 1210 | Supervisor | `handle_turn({kind:'voice', text:'forget the email — just tell me what Cron costs.'})`. `compute_respond_via` → `voice_and_chat`, `replace`. |
| 1500 | Main | Reads task_board: p2 `waiting_user`, r1 `done (Cron $5/u/mo)`. User intent: cancel p2, answer Cron pricing. |
| 1510 | Main | Emits `[STOP_TASK task_id=p2]`. Then speaks: *"Cron is $5 per user per month. Want me to also tell you what's free vs paid?"* |
| 1515 | Supervisor | Cancels p2 worker. Writes `tasks.status='cancelled'`. Emits `event{kind:'task_done', task_id:'p2', summary:'cancelled'}`. |
| 1520 | Transport | `begin_tts_with_echo_suppression(new_turn_id)`. `stop_capture` sent. Caption and audio stream. |

User hears the answer ≈ 1.0 s after finishing speaking. p2 pill goes red. r1 pill stays green.

### 13.6 Device handover — user switches to mobile

User closes laptop. WS closes. Supervisor lingers 60 s (`SESSION_LINGER_SECONDS`), then calls `persist_session_snapshot()` and releases slot 0's KV.

15 minutes later, user opens mobile app. Mobile sends `hello{client:'ios', capabilities:{aec:true, vad:true, wake:true, tts:true}, session_id:null}`.

| Component | Action |
|---|---|
| `ws_endpoint` | `auth.verify_token(new_jwt)` → `user_id=u_42`. |
| `enforce_session_singleton(u_42, new_ws)` | Finds existing (persisted) session for u_42. No live WS to supersede (already closed). Creates new WS binding. |
| `load_or_create_session(u_42, None, {client:'ios'})` | Finds `sessions` row for u_42. Restores `session_id=s_X`. Rebuilds warm profile from PG (Redis cache expired). |
| Transport | Sends `welcome{session_id:'s_X', resumed:true, task_board_snapshot:{...}}`. |
| Client (iOS) | Receives `welcome`. Renders activity feed from `task_board_snapshot`: r1 done (green), p2 cancelled (red). |
| `compute_respond_via` default | `capabilities.aec=true` — echo suppression delay reduced to 300 ms for this client. |

User can ask follow-ups immediately. Sub-agents (none active) would have continued if they had been running. Same memory, same history, same session. No re-research.

### 13.7 The user updates a fact; old value is preserved (typed chat → voice reply)

User types (on mobile): *"btw remember my new work email is alex.k@acme.com"*

| Component | Action |
|---|---|
| Supervisor | `handle_turn({kind:'chat', text:'…'})`. |
| `compute_respond_via` | Mobile, `capabilities.tts=true`, `client_state.playback='idle'`, `visible=true`, no blocking conditions → **`voice_and_chat`**, `queue`. |
| Main | Emits `[REMEMBER key=email.work value="alex.k@acme.com" source="user_intent"]`. Streams reply: *"Got it — old work email kept on file in case you ever need it."* |
| Transport | `begin_tts_with_echo_suppression(turn_id)`. `stop_capture` sent. Caption emitted. Audio streams (AEC mode: 300 ms suppression delay). |
| `memory.facts.set` | Old `alex@acme.com` → `active=false, superseded_by=f_91`. New `alex.k@acme.com` → `active=true`. `warm.dirty=True`. |
| End of turn | `chat_message{text:"Got it — old work email kept on file in case you ever need it.", final:true}`. |

User hears the reply AND sees the text in the mobile chat. The warm block rebuilds next turn.

### 13.8 Days later — historical recall (voice, still works)

User (voice): *"What was my old work email?"*

`compute_respond_via` → `voice_and_chat`, `replace`.

Main emits `[RECALL chain key=email.work]`. Result injected: `[(active, 'alex.k@acme.com', 2026-05-09), (superseded, 'alex@acme.com', 2025-12-01 → 2026-05-09)]`.

Main speaks: *"Your previous work email was alex@acme.com. You changed it to alex.k@acme.com on May 9."*

Caption and `chat_message` both sent. User hears and reads.

### 13.9 Background — the summarizer cleans up

(Same as original §13.9. Summarizer extracts `facts_to_persist` from r1, writes them to MemoryOS via `set_fact`. LanceDB updated.)

### 13.10 What the data looks like at the end

**Postgres `facts`:**
```
f_77  email.work            alex@acme.com           active=false  superseded_by=f_91
f_91  email.work            alex.k@acme.com         active=true   source=user_intent
f_92  integrations.calendar.shortlist  ['Cron','Fantastical','Vimcal']  active=true  source=task:r1
```

**Postgres `tasks`:**
```
r1   research      done        result_summary='Cron $5/u/mo, free tier available'  duration=11.2s
p2   productivity  cancelled   result_summary='cancelled by user'  duration=8.7s
```

**Postgres `signals`:**
```
r1  STEP        'picked 3 candidates'
r1  DONE        '… free tier: Cron basic, no free tier: Fantastical, Vimcal'
p2  STARTED     ''
p2  NEEDS_INFO  'gmail compose scope missing'
p2  CANCELLED   'by user request'
(summarizer)  FACT_WRITE   'integrations.calendar.shortlist'
```

**Redis**: signal-bus quiet. warm_cache rebuilt for mobile session.

**llama-server**: slot 0 = Main (mobile session), KV ≈ 5.1k tokens. Slots 1, 2, 3 free. RAM unchanged from boot.

### 13.11 Reconnect / restart (same as before — works identically with singleton rule)

Device handover is now explicitly handled by `enforce_session_singleton()`. The supervisor registry is the canonical source of truth. No state is lost across handovers because all meaningful state lives in Postgres and Redis, not in the WebSocket connection.

### 13.12 What this example proves about the design

| Concern | How the example handles it |
|---|---|
| Multi-step coordination | r1 → r2 dependency expressed in payload; Supervisor enforces. |
| Context purity | Main never saw trafilatura output, gmail OAuth error, or per-step scratchpads. |
| Mid-task user interjection | "Also check free tiers" became an amendment to r1 instead of a new task. |
| Typed chat → voice reply | Turn 2 and Turn 7: typed input, `respond_via=voice_and_chat`, user hears AND reads the reply. |
| Memory updates | Old email kept; new email active; warm rebuilt; chain queryable later. |
| Interrupts | Wake-word kills speech only. p2 (waiting on user) survives until explicitly cancelled. |
| Tool failure | OAuth scope error became a clean NEEDS_INFO signal — never a stack trace at the user. |
| Proactive surfacing | NEEDS_INFO surfaced via voice+chat when AI was silent and client visible. |
| Cancellation | `[STOP_TASK]` directive cleanly removed p2. |
| Echo suppression | `stop_capture` before every TTS block, `start_capture` after suppression delay. AEC clients get shorter delay. |
| Session singleton | Device handover: laptop → mobile. Supervisor reattached, task board snapshotted in `welcome`. |
| Audit | Every signal, every fact write, every task, every turn is in PG, queryable forever. |
| Server 1 boundary | Auth only at handshake. OAuth credentials fetched by tool runner via Server 1, not by Main. |

If this example feels coherent, the architecture is doing its job. If any step feels surprising, that's a bug in the plan — log it as a row in Section 9 and tighten the rule.

---

## 14. Changelog

| Version | Date | Change |
|---|---|---|
| 1.0 | 2026-05-09 | Initial frozen plan. Stack chosen. Step 1 ready. |
| 1.1 | 2026-05-09 | Added §1.1 two-server topology, expanded auth row in §2, added §7.5 Agent vs Sub-agent capability split with directive grammar, added §13 worked example. Diagram reference bumped to v3 (15 pages). |
| 1.2 | 2026-05-09 | Added §7.6 multi-task coordination, §7.7 STEP → user paths, §7.8 PDF-homework multi-tool chain. Diagram page 15 expanded. |
| 1.3 | 2026-05-10 | Added §7.9 unified NEEDS_INFO / mid-task amendment / confirmation / suggestion contract and §7.10 tool access, discovery, ToolEntry, ToolResult, confirmation, tool_search rules. Split task ANSWER_TO from user-delivery RESPOND_VIA. Diagram reference bumped to v3 (16 pages). |
| 1.4 | 2026-05-10 | Added file/image upload contract, client audio control messages, upload env vars, and §7.11 full implementation API map. Diagram reference bumped to v3 (17 pages). |
| 1.5 | 2026-05-16 | Added "Multimodal inputs — deferred" note in §2. Added `doc/roadmap.md` and `implementation_tracker.drawio`. |
| 1.6 | 2026-05-17 | Step 1 complete. Python locked to 3.11. Replaced tracker.drawio with `doc/tracker.md`. Dev setup: cloud Postgres/Redis via `.env`. |
| 1.7 | 2026-05-19 | **Session singleton (§5.0):** one WS per user enforced at connection time; device handover with `session_superseded` + `welcome{resumed:true}` + `task_board_snapshot`; `enforce_session_singleton()` added to API map. **Typed chat → voice by default (Rule 11):** `chat` input defaults to `voice_and_chat` when session is voice-capable; full `respond_via` decision table added as Rule 13 in §7.5; `compute_respond_via()` added to API map. **Echo suppression mandatory (Rule 12):** `begin_tts_with_echo_suppression()` is the only path to `audio_start`; always sends `stop_capture` first; `start_capture` after delay; AEC clients get reduced delay; `SELF_ECHO_SUPPRESSION_DELAY_MS` and `AEC_CLIENT_SUPPRESSION_DELAY_MS` added to env vars. **Text and caption delivery contract (§5.5):** two channels always sent (`caption` sentence-by-sentence, `chat_message` once complete); behavior on TTS failure, interrupt, and rapid typed messages defined; queue depth = 1 pending; `chat_message` event added to §5.3. **Interrupt FSM (§7.5):** complete state machine table added; queue depth, queue replacement, and queue clearing on interrupt all specified. **`welcome` payload** updated with `resumed` and `task_board_snapshot` fields. **§13 worked example** updated: Turn 2 shows typed chat → voice reply with echo suppression; Turn 3 shows interrupt clearing echo suppression immediately; device handover in §13.6 exercises singleton rule. |
| 1.7+ | 2026-06-07 | **Post-Step-10 main-agent amendments (§7.10.1):** native `tool_calls` via `complete_chat`; single `prompts/main.txt` + `build_main_chat_messages()` session context (today's date, warm, task board); `speak_web_search_results()` for grounded live facts; `tool_fallback.py` / `prose.py` model-output safety nets (no user-keyword routing); typed-chat queue + playback grace (`chat_queue.py`, `session_busy.py`); `revoice_final` when streaming TTS spoke bad partials. Folder map updated for `tool_fallback.py`, `prose.py`, transport helpers. |