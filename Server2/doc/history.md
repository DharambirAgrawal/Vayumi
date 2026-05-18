# History

This log tracks updates pushed to GitHub for Server2. Each entry should be small, factual, and tied to the plan and diagram when relevant.

## How to log

- One entry per push or merged PR.
- Keep the title short and specific.
- Include verification steps or note N/A.
- Reference plan sections or diagram pages when the change aligns with them.

## Entry template

## YYYY-MM-DD - Short title

**Scope:** docs | infra | transport | voice | engine | orchestrator | tools | memory | client | tests

**Why:** One sentence on the problem or goal.

**Key changes:**
- Change 1
- Change 2

**Files/areas:**
- Path or module area

**Plan/diagram references:**
- PLAN section(s) or diagram page(s)

**Tests/verification:**
- Command(s) run or N/A

**Follow-ups:**
- Next steps, if any

---

## 2026-05-11 - History log created

**Scope:** docs

**Why:** Establish a consistent place to track updates pushed to GitHub.

**Key changes:**
- Added this history log and template.

**Files/areas:**
- doc/history.md

**Plan/diagram references:**
- [PLAN.md](../PLAN.md) v1.4 (2026-05-10)
- [orchestrator_diagram_v3.drawio](../orchestrator_diagram_v3.drawio) (17 pages)
- [doc/step-01.md](step-01.md) (pending)

**Tests/verification:**
- N/A

**Follow-ups:**
- Add an entry for each push or merged PR going forward.

---

## 2026-05-17 - Step 1 complete: Project scaffold + WebSocket echo

**Scope:** infra | transport | client | tests

**Why:** Stand up the server spine — FastAPI, database wiring, auth, WebSocket echo, and a working web client — so every later step plugs into a verified foundation.

**Key changes:**
- FastAPI app with lifespan boot sequence (Postgres → Redis → LanceDB → server_health)
- Pydantic Settings with fail-fast validation; cloud Postgres + Redis (shared infra with Server 1)
- `verify_token()` with RS256 prod path and clean dev bypass (token="dev" when no JWT_PUBLIC_KEY)
- WebSocket endpoint `/ws/v1/session` with echo behavior (JSON + binary PCM)
- Typed Pydantic protocol models (Hello, Chat, AudioStart, AudioEnd, Ping / Welcome, Echo, Pong, Error)
- Reference web client: vanilla JS, AudioWorklet PCM capture, WS connect/send/receive
- structlog logging (JSON prod, pretty dev)
- 17 unit tests for protocol round-trips — all green
- Replaced `implementation_tracker.drawio` with `doc/tracker.md` (markdown progress grid + ASCII architecture flow diagrams)

**Files/areas:**
- NEW: `pyproject.toml`, `.env.example`, `.gitignore`, `docker-compose.dev.yml`
- NEW: `server/{__init__,app,config,logger,auth}.py`
- NEW: `server/db/{__init__,postgres,redis,lancedb}.py`
- NEW: `server/transport/{__init__,ws,protocol}.py`
- NEW: `web-client/{index.html,client.js}`
- NEW: `tests/{__init__,conftest}.py`, `tests/unit/test_protocol.py`
- NEW: `doc/tracker.md`
- DELETED: `implementation_tracker.drawio`
- CHANGED: `PLAN.md` (step 1 ⬜→✅, tracker reference updated)
- CHANGED: `doc/roadmap.md` (step 1 ⬜→✅, tracker reference updated)
- CHANGED: `agent-prompt.md` (tracker reference updated)

**Plan/diagram references:**
- PLAN.md §2 (stack), §4 (folder structure), §5 (WS protocol), §10 (env vars), §11 (deps)
- Diagram pages 01 (system overview), 02 (transport), 03 (auth), 14 (boot sequence)

**Tests/verification:**
- `ruff check server/ tests/` — all checks passed
- `pytest tests/unit -q` — 17 passed
- Server boots cleanly against cloud Postgres + Redis: "postgres ok / redis ok / lancedb ok / dev mode: auth bypass enabled / app.ready"
- Web client loads at `http://localhost:8080`

**Follow-ups:**
- Step 2: Engine plane (llama-server runner + slot pool + main-only completion)

---

## 2026-05-18 - Step 2 complete: Engine plane + streamed captions

**Scope:** engine | transport | client | infra | tests

**Why:** Replace typed-chat echo with the real Main Agent engine path while keeping the Step 1 transport proof working.

**Key changes:**
- Added `llama-server` subprocess lifecycle, health polling, graceful shutdown, and fail-fast boot validation.
- Added the engine priority queue shape with P0/P1/P2 priorities, slot accounting, and slot 0 sticky Main completion.
- Added Main-only prompt assembly with `prompts/main.txt`.
- Routed WebSocket `chat` messages through the engine and streamed model output as `caption` messages.
- Kept ping/pong, hello/audio echo, binary PCM echo, and invalid-token rejection working.
- Added optional engine overrides to `.env.example` while keeping ordinary defaults in `server/config.py`.
- Masked Redis credentials in logs and disabled asyncpg statement caching for Supabase pooler compatibility.
- Added unit tests for engine runner, pool streaming, prompt assembly, captions, and Redis log masking.

**Files/areas:**
- NEW: `server/engine/{__init__,runner,pool,prompt}.py`
- NEW: `prompts/main.txt`
- NEW: `tests/unit/{test_engine_runner,test_engine_pool,test_engine_prompt,test_db_redis}.py`
- CHANGED: `server/{app,config}.py`
- CHANGED: `server/db/{postgres,redis}.py`
- CHANGED: `server/transport/{ws,protocol}.py`
- CHANGED: `web-client/{client,index}.html`
- CHANGED: `pyproject.toml`, `.env.example`
- CHANGED: `PLAN.md`, `doc/roadmap.md`, `doc/tracker.md`, `doc/step-02.md`, `agent-prompt.md`

**Plan/diagram references:**
- PLAN.md §2 (LLM runtime / engine pool), §3.3 (Engine plane), §5.3 (`caption`), §7.11 (Engine and prompt API), §8 Step 2, §10 (environment variables), §11 (`httpx`)
- Diagram pages 02 (boot sequence), 05 (chat turn), 06 (engine pool), 17 (API map)

**Tests/verification:**
- `python -m pytest tests/unit -q` — 26 passed
- `ruff check server/ tests/` — all checks passed
- `python -m uvicorn server.app:app --port 8080` — boots cleanly against cloud Postgres/Redis, local LanceDB, and Homebrew `llama-server`
- Web client static route returned HTTP 200
- Live WebSocket check with token `dev`: `welcome`, `hello` echo, `pong`, binary PCM echo, streamed `caption` partials, final `caption partial=false`
- Invalid token check closes with WebSocket code `4401`

**Follow-ups:**
- Step 3: Voice plane (Groq STT + Kokoro TTS + interrupt)

---

## 2026-05-17 - Step 3 complete: Voice plane + interrupt

**Scope:** voice | transport | client | infra | tests

**Why:** Add the first speak-and-hear loop on top of the Step 2 engine path, with interrupts that stop user-facing speech only.

**Key changes:**
- Groq Whisper STT behind `STTBackend.transcribe_stream()`; utterance PCM buffered on `audio_end`.
- Kokoro TTS streaming with 16 kHz PCM frames and server `audio_start` / `audio_end` messages.
- Silero VAD wrapper for server-side/tests.
- `InterruptController` FSM (`IDLE → LISTENING → THINKING → SPEAKING`) with `handle_interrupt`, `cancel_tts`, `cancel_main_decode`.
- WebSocket routes mic capture → STT → Main (P0) → captions + TTS; typed `chat` stays captions-only.
- Web client TTS playback queue and Interrupt button.
- Boot validation for `GROQ_API_KEY` and `KOKORO_MODEL_DIR`.
- 14 new unit tests (40 total).

**Files/areas:**
- NEW: `server/voice/{types,boot,turn,interrupt}.py`, `server/voice/stt/{base,groq}.py`, `server/voice/tts/kokoro.py`, `server/voice/vad/silero.py`
- NEW: `tests/unit/test_voice_*.py`, `doc/step-04.md` (stub)
- CHANGED: `server/{app,config}.py`, `server/transport/{ws,protocol}.py`, `web-client/{index.html,client.js}`, `pyproject.toml`, `.env.example`
- CHANGED: `PLAN.md`, `doc/{step-03,roadmap,tracker,history}.md`

**Plan/diagram references:**
- PLAN.md §3.2 (Voice plane), §5 (WS protocol audio + interrupt), §7.11 (voice API), §8 Step 3, §10–§11 (env + deps)
- Diagram pages 04 (voice turn), 10 (interrupt FSM)

**Tests/verification:**
- `python -m pytest tests/unit -q` — 40 passed
- `ruff check server/ tests/` — all checks passed

**Follow-ups:**
- Step 4: Web client v1 polish (`client_state` / `client_control`, UI)
