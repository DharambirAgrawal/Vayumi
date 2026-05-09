# Vayumi Server 2 — Master Plan

**Version:** 1.2  
**Status:** Architecture locked, Step 1 ready to start  
**Last updated:** 2026-05-09  
**Companion files:** `doc/step-01.md` (current), `doc/step-NN.md` (next)  
**Reference diagram:** `orchestrator_diagram_v3.drawio` (15 pages — visual companion to this plan)  
**Sister service:** `Server1/` (TypeScript) — owns auth, identity, sessions, push tokens. Already implemented and verified.

> **How to use this document:** This plan + the v3 diagram are the *complete* spec. If you (or any future agent) read these two end-to-end you have everything you need to build, debug, or extend Vayumi. If a question is not answered here, the answer is "open a step file or extend §13 / §7.6"; do not improvise.

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

Voice-first multi-agent assistant. User talks (or types). A **Main Agent** running a local Gemma 3n model holds the conversation, owns speech, and delegates tool-heavy work to **Sub-Agents** that share the same model engine through a priority queue. Memory is layered (warm profile, on-demand retrieval, versioned facts). Sub-agents only speak through the Main Agent. Background tasks run in parallel; results surface as proactive notifications when the user is silent. Clients are interchangeable (web, mobile app, ESP32 hardware) because the only contract is one WebSocket protocol.

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
| **Transport** | **WebSocket only**, with a clean `Transport` interface so a future WebRTC swap is a single class | Plain WS works on browser, mobile, and ESP32. Echo cancellation is the *client's* responsibility (the device hardware on ESP32, the browser's `echoCancellation: true` constraint on web, the OS audio session on mobile). The server assumes echo-canceled mono 16 kHz PCM in. |
| **Memory** | **Hybrid: Postgres (versioned facts + sessions) + LanceDB (embedded, semantic retrieval)** | Postgres gives ACID, versioned chains, and superseded history exactly as your diagram needs. LanceDB is a single Python import, disk-backed, scales to millions of vectors, and its versioning maps cleanly to your "superseded fact" model. **No external memory framework** (Mem0/Letta/Zep/MemoryOS) — we own the schema, we own the API, we never get blocked by an upstream library decision. mem0's *fact extraction prompt* is good prior art and we will borrow that pattern. |
| **Embeddings** | **`bge-small-en-v1.5` via `sentence-transformers` ONNX** | 33M params, runs on CPU in milliseconds, MIT-licensed, top of the small-model leaderboard. |
| **Tools** | **Native Python tool registry first, MCP adapter second** | A tool is just a typed Python function plus a JSON schema, registered in `tools/__init__.py`. We add an **MCP client adapter** (using the official `modelcontextprotocol` Python SDK) so any MCP server (filesystem, GitHub, Notion, etc.) shows up as tools without touching agent code. This gives you "easy to add anything" with zero lock-in. |
| **Web search tool** | **Tavily** (free tier 1k/mo) with **DuckDuckGo HTML scrape** as a no-key fallback | Tavily already returns clean snippets; DDG fallback means dev never blocks on API keys. |
| **HTML scraping** | **trafilatura** (best-in-class for article extraction in 2026) | Used by the `summarize_url` sub-agent tool. |
| **Auth** | **Trust Server 1's JWT, nothing else.** Verify RS256 signature offline + check shared Redis blocklist | Server 1 already owns login, register, password reset, OAuth, sessions, push tokens. Server 2's auth is **30 lines of code** (`server/auth.py`): decode token → validate exp/iat/claims → `GET blocklist:<jti>` in shared Redis → return `TokenPayload(user_id, session_id, scopes)`. After that, every WebSocket connection has a verified `user_id` and Server 2 *never thinks about auth again*. We wire this in Step 1 once and forget. There is no user table on Server 2. There is no login endpoint on Server 2. There is no password code on Server 2. If a token expires mid-session, server emits `event{kind:'token_expiring'}` 5 minutes before exp; client refreshes against Server 1 and reconnects with the same `session_id`. |
| **Datastore** | **Postgres (Supabase) + Redis (shared with Server 1) + LanceDB (local file)** | Postgres for facts/sessions/conversations. Redis for the JWT blocklist + signal bus + pub/sub between proactive notifier and orchestrator. LanceDB is a folder on disk for vectors. |
| **Async runtime** | **`asyncio` only**. No threads, no multiprocessing for orchestration | Keeps the model simple. The `llama-server` binary is the only subprocess we manage. |
| **Logging** | **structlog + OpenTelemetry-friendly JSON** | Every turn gets a `turn_id`. Every sub-agent gets a `task_id`. Every signal carries both. You can `grep turn_id=xxx` and see the entire flow. |
| **Tests** | **pytest + pytest-asyncio + a recorded-LLM fixture** | We record `llama-server` responses for fixed prompts and replay them in CI so tests don't need a model. |
| **Frontend reference client** | **Plain HTML + vanilla JS in `web-client/index.html`** | Single file. ~150 LoC. Demonstrates: mic capture, WS connect, PCM upload, audio playback, captions, interrupt button, chat box. No framework, no build step. **This is the "we won't get stuck on the client at the end" guarantee.** |

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
- `supervisor.py`: the per-session brain. One instance per WS connection.
- `directives.py`: parses `[DELEGATE]`, `[STOP]`, `[ANSWER_TO]`, `[REMEMBER]` blocks from Main's stream. **Discarded if interrupt fires mid-block** (page 9 of the diagram, "interrupt safety guarantee").
- `signal_bus.py`: in-process asyncio queue for sub-agent → main signals (`STEP`, `NEEDS_INFO`, `DONE`, `ERROR`).
- `notifier.py`: background loop that drains the signal bus and fires synthetic turns when the user is silent.
- `task_board.py`: the canonical structure that goes into context for Main on every turn — running tasks, latest signals, blocked tasks.

### 3.5 Sub-agent plane (`server/subagents/`)
- `worker.py`: one ephemeral conversation per task. Uses an engine slot. Sees only its capability's tools. Output schema is locked: it must call `report(STEP|DONE|NEEDS_INFO|ERROR, payload)`.
- `capabilities/`: one folder per capability bundle (`research/`, `productivity/`, `comms/`, `data/`). Each declares which tools it owns and a sub-agent prompt.

### 3.6 Tool plane (`server/tools/`)
- `registry.py`: one place where every tool is registered: `(fn, json_schema, capability, requires_auth)`.
- `tools/web_search.py`, `tools/memory_*.py`, `tools/summarize_url.py`, etc. — each is a typed function returning a string. They do not know they live inside an LLM.
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
│   ├── step-01.md                   current step (always exactly one)
│   ├── step-02.md                   next step (planned, not started)
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
│   │   └── protocol.py              JSON message types (typed)
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
│   │   └── task_board.py
│   ├── subagents/
│   │   ├── worker.py
│   │   └── capabilities/
│   │       ├── research/
│   │       ├── productivity/
│   │       ├── comms/
│   │       └── data/
│   ├── tools/
│   │   ├── registry.py
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

### 5.1 Message envelope

- **Binary frames** = raw 16-bit PCM mono 16 kHz audio. Always direction is implicit: client→server is mic, server→client is TTS.
- **Text frames** = JSON. Every JSON message has exactly two top-level fields: `type` and `payload`.

### 5.2 Client → server JSON types

| `type` | `payload` | Meaning |
|---|---|---|
| `hello` | `{ client: "web"\|"ios"\|"android"\|"esp32", capabilities: { aec: bool, vad: bool, wake: bool }, session_id?: str }` | Sent first. Server replies with `welcome`. |
| `chat` | `{ text: string, attachments?: [{kind, url\|data}] }` | Typed message. |
| `audio_start` | `{ sample_rate: 16000, format: "pcm_s16le" }` | Mic stream starting; binary frames follow. |
| `audio_end` | `{}` | End of utterance (client-side VAD decided so). |
| `interrupt` | `{ source: "wake"\|"button"\|"voice" }` | Stop current speech. Background tasks keep running. |
| `mode` | `{ mode: "conversation"\|"meeting" }` | Switch mode. |
| `ping` | `{ t: int }` | Heartbeat. |

### 5.3 Server → client JSON types

| `type` | `payload` | Meaning |
|---|---|---|
| `welcome` | `{ session_id, server_version }` | Reply to `hello`. |
| `caption` | `{ text, partial: bool }` | Live caption of what TTS will speak. |
| `audio_start` | `{ sample_rate, format, turn_id }` | TTS stream starting; binary frames follow. |
| `audio_end` | `{ turn_id }` | TTS done. |
| `event` | `{ kind: "tool_started"\|"tool_done"\|"task_step"\|"task_done"\|"task_error", task_id, summary }` | UX event for the activity feed. |
| `notification` | `{ task_id, text }` | Proactive surface (sub-agent finished while user was idle). |
| `error` | `{ code, message }` | Server-side error the user should know about. |
| `pong` | `{ t }` | Heartbeat reply. |

This protocol is **the only contract between client and server**. It is small, self-describing, and works equally on a browser `WebSocket`, a mobile native socket, or an ESP32 `esp_websocket_client`. Adding an app or hardware client later means *implementing the same protocol*, not redesigning anything server-side.

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

If we miss this on a normal turn, that's a regression and a new step is opened to fix it. Long-input turns get the "I got it, processing in chunks" ack within 300 ms (page 2 of the diagram, "long-input protection").

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
9. **Every tool announces intent before it runs.** UX rule: the user always knows what's happening.
10. **Every step ships with the web client working.** No "we'll integrate the client later."

---

## 7.5 Agent vs Sub-agent — the exact capability split

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
[ANSWER_TO chat|voice|both]
```

These are the **only** directives Main can emit. Anything else is plain text → goes to TTS / chat. The orchestrator's parser is small (≈ 80 lines of regex + Pydantic validation) and lives in `server/orchestrator/directives.py`.

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
4. TTS / chat is Main only.

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

## 8. Phase plan (the order in which we build)

Each phase is one or more `doc/step-NN.md` files. Status here is the source of truth.

### Phase 1 — Spine (in progress)

The minimum that proves the architecture is real. End of phase 1 you can talk to Vayumi from the web client, it understands you, replies in voice, and uses one tool. No sub-agents yet.

| # | Step | File | Status |
|---|---|---|---|
| 1 | Project scaffold + config + db/redis/lancedb wiring + Server 1 JWT auth + WebSocket echo | `doc/step-01.md` | ⬜ next |
| 2 | Engine plane: `llama-server` runner + slot pool + main-only completion | `doc/step-02.md` | ⬜ |
| 3 | Voice plane: Groq STT + Kokoro TTS + interrupt | `doc/step-03.md` | ⬜ |
| 4 | Web client v1 (single HTML file): mic, WS, captions, playback, interrupt button | `doc/step-04.md` | ⬜ |
| 5 | Memory v1: warm profile + session history + Postgres versioned facts | `doc/step-05.md` | ⬜ |
| 6 | Tool plane: registry + `web_search` (Tavily/DDG) + Main can call it | `doc/step-06.md` | ⬜ |

### Phase 2 — Multi-agent

| # | Step | Status |
|---|---|---|
| 7 | Sub-agent worker + signal bus + `report()` schema | ⬜ |
| 8 | Capability bundles + per-capability prompts + 3 capabilities (research, productivity, comms) | ⬜ |
| 9 | Proactive notifier + synthetic turn pipeline | ⬜ |
| 10 | LanceDB retrieval tool + memory_recall on-demand | ⬜ |
| 11 | Summarizer (P2) + automatic compression at 20k tokens | ⬜ |

### Phase 3 — Modes & polish

| # | Step | Status |
|---|---|---|
| 12 | Meeting mode (diarization-friendly transcript accumulation, post-meeting summary) | ⬜ |
| 13 | Local STT fallback (faster-whisper) + offline mode flag | ⬜ |
| 14 | Server-side wake-word echo trap (anti-self-trigger when TTS is playing) | ⬜ |
| 15 | Long-input ack + chunked async doc analysis | ⬜ |
| 16 | MCP adapter — connect arbitrary MCP servers, mirror their tools | ⬜ |

### Phase 4 — Clients & deploy

| # | Step | Status |
|---|---|---|
| 17 | Mobile reference client (React Native or Flutter — your pick) | ⬜ |
| 18 | ESP32 firmware + protocol port | ⬜ |
| 19 | Production hardening: backpressure, reconnection, rate limits | ⬜ |
| 20 | Observability dashboard | ⬜ |

---

## 9. The "did we get unstuck" checks

Past restarts happened because of these specific traps. Each is now a hard rule.

| Trap | Hard rule |
|---|---|
| "Loaded the model multiple times" | The engine plane is the **only** place that talks to `llama-server`. There is exactly one runner. Sub-agents do not import the engine; they go through `pool.submit(...)`. |
| "Subagent context bled into main" | Subagents never write to the main session history. They `report()` to the signal bus. Only the supervisor decides what enters main's context. |
| "Memory got hallucinated" | Facts only get written via `memory_save` (typed args) or the post-turn summarizer (typed extraction schema). Never inferred from free text inside the main loop. |
| "Tool calling broke multi-step" | Main does **not** do raw OpenAI tool-calling. It writes `[DELEGATE capability=research goal="…"]` directives. The orchestrator parses, validates, spawns. Single-step tools (web_search, memory_save) are still directives, just shorter ones. This isolates Main from tool schemas entirely. |
| "Voice and chat fought over state" | Both go through `supervisor.handle_turn(input)`. There's one turn pipeline; voice and chat are just two different `input.kind` values. |
| "The client integration broke at the end" | The web client is in the repo from step 1. Every step has an acceptance test that includes "the web client still works." If it doesn't, the step is not done. |
| "Async deadlocks during interrupts" | One asyncio event loop. Every long-running coroutine has a `cancel_scope`. Interrupt = cancel the speech scope only. Tasks live in their own scope. |
| "Stack got out of date" | This `PLAN.md` is the source of truth. If a library is replaced, we add a row to the changelog and update Section 2. We don't switch silently. |

---

## 10. Environment variables

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
KOKORO_MODEL_DIR=./models/kokoro
KOKORO_VOICE=af_heart

# Embeddings
BGE_MODEL_PATH=./models/bge-small-en-v1.5.onnx

# Tools
TAVILY_API_KEY=                     # optional; falls back to DDG
MCP_SERVERS_JSON=./config/mcp.json  # optional; declares MCP servers to mirror
```

---

## 11. Initial dependencies (Python 3.12)

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

- **`doc/step-01.md`** — the only step you should be working on right now.
- The next step file (`step-02.md`) is allowed to exist *only as a stub* until step 1's acceptance tests pass.
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

This section is the **acceptance test for understanding**. If you can follow every step and explain *why* each thing happens, you understand the system. It exercises: voice + chat, two parallel sub-agents, a mid-task user interjection, a memory update with versioning, a `[RECALL]`, an interrupt that does NOT kill background tasks, a sub-agent `NEEDS_INFO`, a tool failure with recovery, and the proactive notifier surfacing two completions.

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

### 13.1 Turn 1 — User gives a multi-step goal (voice)

**User says:** *"Hey Vayumi — find three calendar-sharing apps that work on iOS and Android, compare pricing, and draft an email to my team recommending one."*

What happens, in order, with timestamps relative to when the user finished speaking:

| t (ms) | Component | Action |
|---|---|---|
| 0 | Client (web) | Local Silero VAD signals end-of-utterance. Sends `audio_end`. |
| ~250 | Voice plane | Groq Whisper streaming returns FINAL transcript. |
| 260 | Supervisor | `handle_turn(input={kind:'voice', text:'...'})`. State `LISTENING → THINKING`. |
| 265 | Memory plane | Concurrent fetch: warm profile (cached, free), recent history (8 turns from PG), task_board snapshot (empty), drain signal_bus (empty). |
| 320 | Engine pool | Build Main prompt: system + warm + history + user_msg ≈ 3.0k tokens. Submit P0 to slot 0. |
| 700 | Main (slot 0) | First token arrives. Begins streaming. |
| 720 | Directives parser | Reads first 30 tokens — they're plain text. Pipes them to TTS as a sentence: *"Got it — I'll find apps and start a draft in parallel."* |
| 800 | Voice plane | Kokoro emits first 20 ms PCM frame for that sentence. |
| 850 | Transport | First audio frame leaves the WebSocket. **User hears the start of the reply at ~1.0 s.** State `THINKING → SPEAKING`. |
| 1100 | Main (still streaming) | Emits two directive blocks back-to-back: |

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
| 1101 | Directives parser | Parses both. Validates capability + payload schemas. The second has `blocked_on:"r1_done"` — Supervisor will hold its actual run until r1 reports DONE; the row exists immediately on the task_board with status `blocked`. |
| 1110 | Supervisor | `spawn_subagent(research, …)` → creates `task_id=r1`, allocates slot 1, status `running`. Writes to PG: `tasks(id=r1, user_id=u_42, capability='research', status='running', goal='…')`. |
| 1115 | Supervisor | Creates `task_id=p2`, status `blocked` (waiting on r1). Adds to task_board. |
| 1120 | Transport | Emits `event{kind:'tool_started', task_id:'r1', summary:'Researching calendar-sharing apps'}` and same for p2 (with note "queued, depends on r1"). |
| 1200 | Main (slot 0) | Continues with one closing sentence: *"I'll let you know when the comparison is ready."* Emits `[ANSWER_TO voice]`. Then stops. State `SPEAKING → IDLE`. |

**What the user sees / hears:** voice reply ≈ 1.0 s in, two activity-feed pills appear ("Researching calendar-sharing apps" with a spinner; "Drafting team email" with "queued").

**What's in memory after Turn 1:** nothing new written. The user's request itself is a turn row in PG `turns` (raw); not yet a fact.

### 13.2 Sub-agents r1 and r2 start working

Concurrent with everything above:

| Component | Action |
|---|---|
| `SubAgentWorker(r1)` | Loads `prompts/sub/research.txt` + tool schemas for `research` bundle: `web_search`, `fetch_html`, `summarize_url`, `memory_recall`. Builds prompt: system + capability_prompt + tool_schemas + goal + payload. Submits P1 to slot 1. |
| Slot 1 | Llama begins decoding r1's plan. Output starts with `[CALL web_search query="best calendar sharing apps iOS Android 2026"]`. |
| Orchestrator (tool runner) | Intercepts. Runs `web_search` (Tavily). Returns 8 result snippets as a tool-result message injected into r1's context. |
| Slot 1 (r1) | Reads results, picks 3 candidates: "Cron", "Fantastical", "Vimcal". Emits `report(STEP, summary="picked 3 candidates: Cron, Fantastical, Vimcal")`. |
| Signal bus | STEP signal → Supervisor.signal_drainer updates `task_board[r1].latest_progress`. **No LLM call on Main.** |
| Transport | Emits `event{kind:'task_step', task_id:'r1', summary:'picked 3 candidates'}`. The activity-feed pill updates. |
| Slot 1 (r1) | Next: `[CALL fetch_html url="https://cron.com/pricing"]`. |
| Tool runner | trafilatura extracts main article content; truncates to 2k tokens; returns. |
| (×3) | Same for the other two sites, in this slot. |
| Slot 1 (r1) | Emits a normalized comparison + `report(DONE, summary='Done. Cron $5/u/mo, Fantastical $5/u/mo, Vimcal $20/u/mo. Cron and Fantastical are closest match.', payload={table:[…], recommended:'Cron', facts_to_persist:[{key:'integrations.calendar.shortlist', value:['Cron','Fantastical','Vimcal']}]})`. |

Sub-agent r1 is done. Slot 1 is freed. r2 was blocked on r1, so the supervisor unblocks it.

### 13.3 r2 (productivity sub-agent) starts; meanwhile user interjects (chat)

While r2 is starting up, the user (still on web) **types** in the chat box: *"oh — also CC my manager"*.

| t | Component | Action |
|---|---|---|
| ~1.5s after r1 DONE | Supervisor | Promotes p2 from `blocked` to `running`. Allocates slot 1 (just freed). Builds prompt with: capability_prompt(productivity) + tool_schemas(productivity) + goal + payload. Critically: **payload now also includes the condensed r1 result** as a "context block" so r2 doesn't re-research. Submits P1. |
| immediately | Transport | Receives the user's typed `chat` message. |
| immediately | Supervisor | New input arrives. State is IDLE → handle_turn(input={kind:'chat', text:"oh — also CC my manager"}). |
| t+5 ms | Memory plane | Concurrent fetch as before, **plus** task_board snapshot now contains: `r1=done (with summary)`, `p2=running (just spawned)`. |
| t+50 ms | Main prompt | system + warm + history + task_board condensed view + new user_msg. The task_board section is roughly: `Tasks in flight: p2 (productivity, drafting team email). Just completed: r1 (research, picked Cron).` — it does NOT include r1's full result, just the summary; that detail was passed only to r2. |
| t+400 ms | Main streams | *"Got it, adding your manager."* Emits: |

```
[RECALL key=relationships.manager.email]
```

| t | Component | Action |
|---|---|---|
| t+401 | Directives parser | Pauses Main's stream (suspends decoding on slot 0), runs `memory.facts.get('relationships.manager.email')` → returns `'priya@acme.com'`. Re-injects as `[RECALL_RESULT priya@acme.com]` into Main's context. |
| t+450 | Slot 0 (Main) | Resumes. Emits: |

```
[DELEGATE capability=productivity
   goal="update the in-flight email draft to also CC priya@acme.com"
   payload={"task_ref":"p2","cc":["priya@acme.com"]}]
```

| t | Component | Action |
|---|---|---|
| t+460 | Supervisor | Sees `task_ref:"p2"` — instead of spawning a new task, it appends an *amendment* to p2's input queue. p2 is already running on slot 1 and will pick this up at its next reasoning step. |
| t+500 | Main | Closes with: *"Will do."* Emits `[ANSWER_TO voice]`. State → IDLE. |

**Key thing:** Main never opened the email draft itself. It does not know what r2 has written so far. It just knew the *user's intent* (add a CC) and forwarded it via an amendment to p2.

### 13.4 r2 hits a problem — `NEEDS_INFO`

p2 (now on slot 1) reads its prompt + the freshly appended amendment. It begins drafting. It tries to call `gmail.draft_create`:

| Component | Action |
|---|---|
| Slot 1 (p2) | `[CALL gmail.draft_create to=team@acme.com cc=priya@acme.com subject="…" body="…"]` |
| Tool runner | Calls the gmail tool. The gmail tool calls Server 1's `oauth_integrations` endpoint to fetch the user's gmail token. Server 1 returns: `403 SCOPE_INSUFFICIENT` — the user has connected gmail with read-only scope. |
| Tool runner | Returns a structured error string to p2: `{"error":"oauth_scope_missing","scopes_needed":["gmail.compose"],"how_to_fix":"client must reconnect gmail with compose scope via Server 1"}`. |
| Slot 1 (p2) | Reads the error. Knows from prompt that it cannot resolve OAuth itself. Emits `report(NEEDS_INFO, summary="Need gmail compose scope to send a draft", payload={action:"reconnect_gmail_compose"})`. |
| Signal bus | NEEDS_INFO with importance=1.0. |
| Notifier (next tick) | Gates pass: AI not speaking, debounce ok, importance high. Builds a synthetic chat-only turn for Main. |

### 13.5 Main surfaces the NEEDS_INFO

A synthetic turn fires: `handle_turn({kind:'proactive', signals:[{task:p2, kind:NEEDS_INFO, summary:…}], respond_via:'chat_only'})`.

Main reads it, writes to chat:

> *"Quick blocker on the email draft — your gmail is connected as read-only. Want me to open the reconnect flow so I can draft on your behalf? Otherwise I can give you a copy-pasteable text right here."*

State → `WAIT_USER`. Activity-feed pill for p2 turns yellow.

### 13.6 User chooses "give me the text", interrupts, then changes mind

User (voice): *"Just give me the text he—"* — and at that moment **the user changes their mind mid-sentence and says louder: "Vayumi, stop. Forget the email — just tell me what Cron costs."**

This is an interrupt mid-utterance. What happens:

| t | Component | Action |
|---|---|---|
| 0 | Client | Wake-word fires again ("Vayumi"). Client sends `interrupt{source:'wake'}`. Begins capturing the new utterance. |
| 5 ms | Supervisor | Speech FSM: any state → LISTENING. |
| 5 ms | Voice plane | TTS generator (none active right now) — no-op. |
| 5 ms | Engine pool | Slot 0 (Main) — Main was idle. No completion to cancel. |
| 5 ms | Directive buffer | Empty. Cleared anyway. |
| 5 ms | Background tasks | **Untouched.** p2 is still in WAIT_USER on the orchestrator side, but slot 1 is free — p2's worker is suspended awaiting input, not running. |
| ~250 | Voice plane | New STT FINAL: *"Just give me the text he"* — the *aborted* first utterance. Supervisor sees this as an in-flight transcript whose audio was followed by a wake interrupt; it is dropped (the transcript would have been a turn input, but interrupt fired before `audio_end`). |
| ~700 | Voice plane | Second STT FINAL: *"forget the email — just tell me what Cron costs."* This is the real next turn. |
| 710 | Supervisor | `handle_turn({kind:'voice', text:'forget the email — just tell me what Cron costs.'})`. |

Main's prompt now has the task_board showing `p2 (waiting_user)` and `r1 (done)`. The user's intent is two things:

1. *Cancel p2.* Main emits: `[STOP_TASK task_id=p2]`. Supervisor cancels the worker, frees its blocked-on-user state, writes `tasks.status='cancelled'`, emits `event{kind:'task_done', task_id:'p2', summary:'cancelled by user'}`.
2. *Answer about Cron pricing.* Main has the r1 summary in task_board (which says "Cron $5/u/mo"). It answers immediately:

> *"Cron is $5 per user per month. Want me to also tell you what's free vs paid?"*

User hears it ≈ 1.0 s after finishing speaking. p2's pill goes red ("cancelled"). r1's pill stays green.

### 13.7 The user updates a fact; old value is preserved

User (chat, while still talking voice): *"btw remember my new work email is alex.k@acme.com"*

| Component | Action |
|---|---|
| Supervisor | `handle_turn({kind:'chat', text:'…'})`. |
| Main | Reads, emits: |

```
[REMEMBER key=email.work value="alex.k@acme.com" source="user_intent"]
```

| Component | Action |
|---|---|
| Directives parser | Validates. Calls `memory.facts.set('email.work', 'alex.k@acme.com', source='user_intent')`. |
| `memory.facts.set` | Begins PG transaction. Selects the active row for `email.work` → finds `alex@acme.com` (`id=f_77`). Updates it: `active=false, superseded_at=now(), superseded_by=NEW_ID`. Inserts new row `(id=f_91, key='email.work', value='alex.k@acme.com', active=true, source='user_intent', confidence=1.0, created_at=now())`. Re-embeds the value (bge-small) and upserts the embedding into LanceDB `facts_index` keyed by `f_91`. Sets `warm.dirty=True`. Commits. |
| Main | Closes with: *"Got it — old work email kept on file in case you ever need it."* |

The next turn that runs (any kind), the Supervisor sees `warm.dirty=True` and rebuilds the warm profile (includes the new value, drops the old from L1). `warm.dirty=False` again.

### 13.8 Days later — historical recall (still works, with zero context cost)

User (voice, on mobile this time): *"What was my old work email?"*

| Component | Action |
|---|---|
| Supervisor | New voice turn. Main does NOT have the old email in its context (warm has only the active value). |
| Main | Emits: `[RECALL chain key=email.work]` |
| Directives parser | Calls `memory.facts.chain('email.work')` → returns ordered list `[(active, 'alex.k@acme.com', 2026-05-09T11:30Z), (superseded, 'alex@acme.com', created 2025-12-01T…, superseded 2026-05-09T11:30Z)]`. Injects as `[RECALL_RESULT …]` into context. |
| Main | *"Your previous work email was `alex@acme.com`. You changed it to `alex.k@acme.com` on May 9."* |

This costs ~80 tokens of context for this one turn. It costs zero on every other turn. That is the entire point of the versioned-fact design.

### 13.9 Background — the summarizer cleans up

About 2 minutes after the storm of activity, when the system is idle:

| Component | Action |
|---|---|
| Summarizer worker (P2, slot 3) | Sees session history is now ~12k tokens. Below 20k threshold; not triggered yet. |
| Summarizer worker (P2) | Triggered explicitly because r1 is DONE: extracts `facts_to_persist` from r1's report. Validates each candidate: the `integrations.calendar.shortlist` fact passes (high confidence, deduped against existing chain). Writes via `memory.facts.set()`. |
| LanceDB | New fact embedded into `facts_index`. |
| Postgres | `tasks` row for r1 is finalized with `result_summary` and `result_full_jsonb` (kept on disk for later [RECALL task:r1] queries). |
| Postgres | `signals` rows for r1 (STEP, DONE) and p2 (NEEDS_INFO, cancelled) are kept indefinitely as audit. |

### 13.10 What the data looks like at the end

**Postgres `facts` (versioned)**:

```
f_77  email.work            alex@acme.com           active=false  superseded_by=f_91
f_91  email.work            alex.k@acme.com         active=true   source=user_intent
f_92  integrations.calendar.shortlist  ['Cron','Fantastical','Vimcal']  active=true  source=task:r1
... (everything else unchanged)
```

**Postgres `tasks`**:

```
r1   research      done        result_summary='Cron $5/u/mo …'  duration=11.2s
p2   productivity  cancelled   result_summary='cancelled by user'  duration=8.7s
```

**Postgres `signals`** (last 6, in order):

```
r1  STEP        'picked 3 candidates'
r1  DONE        '… Cron and Fantastical closest …'
p2  STARTED     ''
p2  NEEDS_INFO  'gmail compose scope missing'
p2  CANCELLED   'by user request'
(summarizer)  FACT_WRITE   'integrations.calendar.shortlist'
```

**LanceDB `facts_index`**: 2 new rows (f_91, f_92). One stale row (f_77 stays — it's never deleted; chain queries need it).

**Redis**: `signal_bus:<session>` channel has been quiet for 90s. `warm_cache:u_42` is fresh (rebuilt after the email change).

**llama-server**: slot 0 = Main, KV ≈ 5.1k tokens. Slots 1, 2, 3 = free. Total RAM unchanged from boot.

### 13.11 Reconnect / device handoff (optional, fits the same example)

User closes the laptop. Web client WS goes away. Supervisor lingers 60 s, then writes `sessions.last_seen=now()`, persists conversation state, releases slot 0's KV (the prefix is rebuildable from history).

User opens the mobile app 30 minutes later. Mobile sends `hello{session_id:'s_X', client:'ios', …}`. Server 2:

1. `auth.verify_token(token)` (the token was refreshed by the iOS keychain logic).
2. Looks up `sessions.s_X` for `u_42`. Found.
3. Re-instantiates Supervisor; warm profile is rebuilt from PG (no Redis cache hit on mobile). Slot 0 prompt prefix rehydrates over the next turn.

Mobile gets a `welcome` event. The activity feed shows the last 24 h of tasks (r1 done, p2 cancelled). User can ask follow-ups against the same memory state. No re-research happens.

### 13.12 What this example proves about the design

| Concern | How the example handles it |
|---|---|
| Multi-step coordination | r1 → r2 dependency expressed in payload (`blocked_on:"r1_done"`); Supervisor enforces. |
| Context purity | Main never saw the trafilatura output, the gmail OAuth error blob, or per-step LLM scratchpads. |
| Mid-task user interjection | "CC my manager" became an *amendment* to p2 instead of a new task. |
| Memory updates | Old email kept; new email active; warm rebuilt; chain queryable later. |
| Interrupts | Wake-word kills speech only. p2 (waiting on user) survives until explicitly cancelled. |
| Tool failure | OAuth scope error became a clean NEEDS_INFO signal — never a stack trace at the user. |
| Proactive surfacing | NEEDS_INFO + DONE both surfaced when AI was silent and importance high enough. |
| Cancellation | `[STOP_TASK]` directive cleanly removed p2. |
| Audit | Every signal, every fact write, every task is in PG, queryable forever. |
| Server 1 boundary | Auth only checked at handshake. OAuth credentials fetched by tool runner via Server 1, not by Main. |

If this example feels coherent, the architecture is doing its job. If any step feels surprising, that's a bug in the plan — log it as a row in Section 9 and tighten the rule.

---

## 14. Changelog

| Version | Date | Change |
|---|---|---|
| 1.0 | 2026-05-09 | Initial frozen plan. Stack chosen. Step 1 ready. |
| 1.1 | 2026-05-09 | Added §1.1 two-server topology, expanded auth row in §2 (Server 1 owns identity; Server 2 only verifies), added §7.5 Agent vs Sub-agent capability split with directive grammar, added §13 worked example (multi-step + parallel sub-agents + interjection + interrupt + memory versioning + recall + cancellation). Diagram reference bumped to v3 (15 pages). |
| 1.2 | 2026-05-09 | Added §7.6 multi-task coordination (no mix-ups), §7.7 STEP → user paths (UI / status question / optional verbal digest) with example phrases, §7.8 PDF-homework multi-tool chain inside one delegate. Fixed stale §14 cross-refs. Diagram page 15 expanded + addendum boxes for §7.6–§7.8. |
