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

---

## 2026-05-17 - Step 4 complete: Web client v1 + client control

**Scope:** client | transport | tests

**Why:** Polish the reference web client into a full voice conversation UI with `client_state` / `client_control` so server and client stay in sync on playback and capture.

**Key changes:**
- Conversation UI: captions bar, chat bubbles, activity feed, mode toggle (meeting stub), toggle mic.
- `client_state` / `client_control` / `mode` / `event` protocol types.
- `server/transport/client_control.py` with `send_client_control`, `handle_client_state`, interrupt → stop/clear_queue, TTS → play.
- Web client reports state after connect, playback/capture changes, and every `client_control`.
- 11 new unit tests (51 total).

**Files/areas:**
- NEW: `web-client/style.css`, `server/transport/client_control.py`, `tests/unit/test_client_control.py`, `doc/step-05.md` (stub)
- CHANGED: `web-client/{index.html,client.js}`, `server/transport/{protocol,ws}.py`, `server/voice/turn.py`
- CHANGED: `PLAN.md`, `doc/{step-04,roadmap,tracker,history}.md`

**Plan/diagram references:**
- PLAN.md §5 (WS protocol), §7.11 (client_control API), §8 Step 4
- Diagram pages 01, 04, 05, 17 (audio control flow)

**Tests/verification:**
- `python -m pytest tests/unit -q` — 51 passed
- `ruff check server/ tests/` — all checks passed

**Follow-ups:**
- Step 5: Memory v1 (warm profile, session history, versioned facts)

---

## 2026-05-17 - Step 5 complete: Memory v1 + supervisor turns

**Scope:** memory | orchestrator | engine | transport | voice | tests

**Why:** Give Main a real memory layer — versioned facts, warm profile, session history, and REMEMBER/RECALL directives — wired into chat and voice turns.

**Key changes:**
- Postgres schema: `facts`, `sessions`, `turns` (versioned fact chains, partial unique on active rows).
- Memory plane: `set_fact` / `get_fact` / `get_chain`, `build_warm_profile` + Redis cache, `append_turn` / `recent_turns`.
- bge-small-en-v1.5 embedder via `sentence-transformers`; LanceDB `facts_index` upsert on write.
- `Supervisor.run_turn` assembles warm + history, streams Main completion, executes directives, RECALL follow-up pass.
- `[REMEMBER]` / `[RECALL]` / `[RECALL chain]` parser in `directives.py`.
- Chat and voice paths route through supervisor; `prompts/main.txt` updated for memory directives.
- 10 new unit tests (61 total).

**Files/areas:**
- NEW: `server/db/schema.sql`, `server/memory/*`, `server/orchestrator/{directives,supervisor}.py`
- CHANGED: `server/db/{postgres,lancedb}.py`, `server/engine/prompt.py`, `server/transport/ws.py`, `server/voice/turn.py`, `server/app.py`, `server/config.py`, `prompts/main.txt`, `pyproject.toml`, `.env.example`
- NEW: `tests/unit/test_{memory_facts,memory_warm,directives,supervisor}.py`, `doc/step-06.md` (stub)
- CHANGED: `PLAN.md`, `doc/{step-05,roadmap,tracker,history}.md`

**Plan/diagram references:**
- PLAN.md §3.7 (Memory plane), §7 (directive grammar), §7.11 (memory API), §8 Step 5, §10–§11
- Diagram page 09 (memory layers)

**Tests/verification:**
- `python -m pytest tests/unit -q` — 61 passed
- `ruff check server/ tests/` — all checks passed

**Follow-ups:**
- Step 6: v1.7 contract backfill (session singleton, respond_via, echo suppression)

---

## 2026-05-21 - v1.7 doc backfill + step renumber

**Scope:** docs

**Why:** Align documentation with PLAN.md v1.7 (session singleton, respond_via, echo suppression, chat_message) and insert a backfill step before tools.

**Key changes:**
- Added Step 06 spec for the v1.7 contract backfill.
- Renumbered tool plane to Step 07 and shifted later steps.
- Updated roadmap, tracker, and diagram references to reflect new contracts and step numbers.
- Updated agent prompt to summarize Rules 11–13.

**Files/areas:**
- `doc/step-06.md`, `doc/step-07.md`
- `doc/roadmap.md`, `doc/tracker.md`, `PLAN.md`
- `orchestrator_diagram_v3.drawio`, `agent-prompt.md`

**Plan/diagram references:**
- PLAN.md v1.7 (§5, §7.5, §7.11, §8)
- Diagram pages 03 (connect/auth), 05 (chat turn), 10 (interrupt)

**Tests/verification:**
- N/A (documentation update)

**Follow-ups:**
- Implement Step 06 backfill, then continue with Step 07 tool plane.

---

## 2026-05-21 - Full doc consistency audit (v1.7)

**Scope:** docs

**Why:** Cross-check all step files, tracker, roadmap, agent prompt, PLAN.md §3.4, and `orchestrator_diagram_v3.drawio` against PLAN.md v1.7 so session singleton, respond_via, echo suppression, and chat_message are aligned with no gaps.

**Key changes:**
- Fixed PLAN.md §3.4 Supervisor wording (per `user_id`, not per WebSocket).
- step-01/03/04/05: v1.7 deliverable notes, acceptance criteria, and session-singleton / echo-suppression tests.
- roadmap.md: repaired corrupted Step 2 section; Step 8/10 v1.7 notifier notes.
- tracker.md: v1.7 contract matrix; deliverable ownership by step.
- Created `doc/step-08.md` (sub-agent) and `doc/step-10.md` (notifier) stubs with `compute_respond_via` requirements.
- orchestrator_diagram_v3.drawio: page 03 singleton flow, page 10 FSM table + Rule 12/13 alignment.

**Files/areas:**
- `PLAN.md`, `doc/{step-01,03,04,05,08,10,roadmap,tracker,history}.md`, `agent-prompt.md`, `orchestrator_diagram_v3.drawio`

**Tests/verification:** N/A (documentation only)

---

## 2026-05-21 - Step 6: v1.7 contract backfill

**Scope:** transport | voice | orchestrator | web-client | tests

**Why:** Align Steps 1–5 with PLAN.md v1.7 before adding the tool plane.

**Key changes:**
- Session singleton: `enforce_session_singleton()` in `session_registry.py`; `session_superseded` event + close code 4001; `welcome{resumed, task_board_snapshot}` after `hello`.
- `compute_respond_via()` (Rule 13); typed chat defaults to `voice_and_chat` when TTS-capable.
- `begin_tts_with_echo_suppression()` (Rule 12): `stop_capture` → TTS → `start_capture` after delay.
- `chat_message` server event distinct from sentence-level `caption`.
- Chat queue depth 1 while assistant is speaking.
- Web client: `capabilities.tts`, `renderChatMessage`, stop/start capture, handover notice.

**Files/areas:**
- NEW: `server/transport/session_registry.py`, `server/transport/chat_queue.py`, `server/voice/respond_via.py`, `server/voice/echo_suppression.py`, `server/voice/delivery.py`, `server/voice/tts_stream.py`
- CHANGED: `server/transport/{ws,protocol,client_control}.py`, `server/voice/{turn,interrupt}.py`, `server/orchestrator/{supervisor,directives}.py`, `server/config.py`, `web-client/client.js`, `.env.example`
- NEW tests: `test_respond_via.py`, `test_session_singleton.py`; updated protocol/interrupt tests

**Plan/diagram references:** PLAN.md §5.0, §5.5, Rules 11–13, §7.11; diagram pages 03, 05, 10

**Tests/verification:**
- `python -m pytest tests/unit -q` — 72 passed
- `ruff check server/ tests/` — all checks passed

**Follow-ups:**
- Step 7: Tool plane

---

## 2026-05-21 - Step 6 completion: PLAN §5.5 streaming TTS

**Scope:** voice | transport | orchestrator | tests | docs

**Why:** Step 6 text delivery required interleaved LLM→TTS (first audio after first sentence), not batch TTS after full generation.

**Key changes:**
- `sentence_buffer.py` — `drain_complete_sentences()` from token stream.
- `streaming_tts.py` — `StreamingTtsPipeline` queues sentences, emits `audio_start` once, PCM per sentence, `audio_end` + echo clear.
- `ws.py` / `turn.py` wire pipeline into `on_token`; `delivery.py` skips batch TTS when `tts_streamed_during_llm`.
- Runtime fixes retained: Kokoro model path, client `audio_start` without `clear_queue`, session_busy mic discard, `cache_prompt: false`, dev session UUID.

**Tests/verification:**
- `python -m pytest tests/unit -q` — 84 passed
- `ruff check server/voice server/transport/ws.py server/orchestrator/supervisor.py` — clean

**Manual check:** restart uvicorn + llama-server; hard-refresh client; long reply should hear first sentence before LLM finishes.

---

## 2026-05-21 - Tracker + history brought current through Step 6

**Scope:** docs

**Why:** Tracker detail sections stopped at Step 4 in the scroll order (Step 3 missing; file map and WS flow still described Step 1 echo).

**Key changes:**
- Added step index table (Steps 1–6 ✅, 7 ⬜) at top of `doc/tracker.md`.
- Added **What Step 3 Built** section; clarified Steps 1–6 complete.
- Replaced Step 1 echo WS diagram with current hello-first + singleton + `chat_message` flow.
- Updated full-system diagram, audio flow, and file map for Step 5–6 modules.

**Files/areas:** `doc/tracker.md`

**Tests/verification:** N/A

---

## 2026-05-21 - Step 7 complete: Tool plane

**Scope:** tools | orchestrator | transport | client | tests

**Why:** Give Main cheap direct tools (search, memory, discovery) through one registry and runner before sub-agents in Step 8.

**Key changes:**
- `ToolRegistry` + `ToolRunner` — single execution path with capability gate, args validation, timeout, audit, and `tool_started`/`tool_done` events.
- Main tools: `tool_search`, `web_search` (Tavily when `TAVILY_API_KEY` set, DuckDuckGo fallback), `memory_save`, `memory_recall`.
- `[DELEGATE capability=main ...]` parsing; `tool_dispatch` runs multiple delegates in parallel; non-main capabilities return `not_capable` until Step 8.
- Supervisor follow-up pass injects `[TOOL_RESULT ...]` (same pattern as RECALL); follow-up blocks recursive DELEGATE.
- Boot: `init_tools()` on `app.state`; chat + voice turns pass `tool_runner` and event emitter to WebSocket activity feed.
- 24 new unit tests (108 total); Phase 1 complete (7/7).

**Files/areas:**
- NEW: `server/tools/{registry,runner,tool_search,web_search,memory_save,memory_recall}.py`, `server/orchestrator/tool_dispatch.py`
- NEW tests: `test_tools_*.py`, `test_directives_tools.py`, `test_supervisor_tools.py`, `test_tool_dispatch.py`
- CHANGED: `server/orchestrator/{directives,supervisor}.py`, `server/{app,config}.py`, `server/transport/ws.py`, `server/voice/turn.py`, `prompts/main.txt`, `web-client/client.js`, `pyproject.toml`, `.env.example`
- CHANGED: `PLAN.md`, `doc/{step-07,roadmap,tracker,history}.md`

**Plan/diagram references:** PLAN.md §3.6, §7.10–§7.11, §8 Step 7, §10–§11; diagram page 08

**Tests/verification:**
- `python -m pytest tests/unit -q` — 108 passed
- `ruff check server/ tests/` — all checks passed

**Follow-ups:**
- Step 8: Sub-agent worker + signal bus (reuse `ToolRunner` without changes)

---

## 2026-05-22 - Step 8 complete: Sub-agent worker + signal bus

**Scope:** orchestrator | subagents | engine | transport | client | tests

**Why:** Run long background work in parallel without blocking Main — Path A task pills, pause/resume, and structured task board for Main context.

**Key changes:**
- `ReportSignal` + `[REPORT kind=...]` parsing; `SubAgentWorker` loop on P1 slots with `submit_assigned` / `free_slot`.
- `SignalBus.publish` + `TaskBoard.upsert_from_signal` / `render_for_main()`; Postgres `tasks` + `signals` tables.
- `spawn_subagent`, `apply_answer_to_task`, `cancel_task`; `[ANSWER_TO]` / `[STOP_TASK]` directives.
- `DELEGATE capability=research|...` spawns background worker; `main` still uses Step 7 `tool_dispatch`.
- WebSocket `task_step` / `task_done` / `task_error` events; `welcome{task_board_snapshot}` always populated.
- Engine pool: `assign_slot` (slots 1–3 for sub-agents), `hold_slot` across worker steps.

**Files/areas:**
- NEW: `server/subagents/{report,worker}.py`, `server/orchestrator/{signal_bus,task_board}.py`, `prompts/sub/research.txt`
- NEW tests: `test_{subagent_worker,signal_bus,task_board,directives_subagent,supervisor_subagent}.py`
- CHANGED: `server/orchestrator/{supervisor,directives,tool_dispatch}.py`, `server/engine/{pool,prompt}.py`, `server/db/schema.sql`, `server/transport/{ws,session_registry}.py`, `server/voice/turn.py`, `prompts/main.txt`, `web-client/{client.js,style.css}`

**Plan/diagram references:** PLAN.md §7.7, §7.11, §8 Step 8; diagram pages 07, 15, 16

**Tests/verification:**
- `python -m pytest tests/unit -q` — 131 passed
- `ruff check server/ tests/` — all checks passed

**Follow-ups:**
- Step 9: Capability bundles (per-capability tool cards, `summarize_url`, full sub prompts)

---

## 2026-05-22 - Deep search + Scrapling fetch tools (research)

**Scope:** tools | orchestrator | subagents | tests

**Why:** Research sub-agents need full article text (not just Tavily snippets) with fast static fetch and optional browser fallback.

**Key changes:**
- `deep_search` — Tavily/DDG discover URLs, then static Scrapling fetch + trafilatura extract per page; snippet fallback on block.
- `fetch_url` — single-URL read with same fetch ladder.
- Registry keyed by `(capability, name)`; research tools: `deep_search`, `fetch_url`, `memory_recall`.
- Sub-agent prompts inject warm profile; `RESEARCH_TOOLS` updated in `tool_dispatch`.
- Deps: `scrapling[fetchers]`, `trafilatura`.

**Tests/verification:**
- `python -m pytest tests/unit -q` — 150 passed
- `ruff check server/ tests/` — clean

## 2026-05-23 - Step 9 complete: Capability bundles

**Scope:** subagents | tools | orchestrator | tests

**Why:** Give each sub-agent domain a declarative bundle (prompt + allowed tools) so the model only sees what it may call, with PLAN-named fetch tools and clean registry structure.

**Key changes:**
- `CapabilityBundle` + `load_capability()` + `render_tool_cards()` under `server/subagents/capabilities/`.
- Manifests for `research`, `productivity`, `comms`; worker injects tool cards via `build_subagent_prompt()`.
- `summarize_url` (trafilatura article text) and `fetch_html` (raw HTML); removed `fetch_url`.
- Kept `deep_search` (search + per-link fetch via `page_fetch`).
- Productivity/comms stub tools with real `user_action_required` / confirmation shapes.
- `tool_dispatch` gates sub-agent tools from bundle `allowed_tools`.

**Files/areas:**
- NEW: `server/subagents/capabilities/{bundle,research,productivity,comms}/`
- NEW: `server/tools/{summarize_url,fetch_html,productivity_draft,comms_email}.py`
- DELETED: `server/tools/fetch_url.py`
- CHANGED: `server/tools/__init__.py`, `server/subagents/worker.py`, `server/orchestrator/tool_dispatch.py`, `server/engine/prompt.py`, `prompts/sub/*.txt`
- NEW tests: `test_capabilities.py`, `test_summarize_url.py`, `test_fetch_html.py`, `test_capability_gates.py`

**Plan/diagram references:** PLAN.md §7.5, §7.11, §8 Step 9; diagram page 08

**Tests/verification:**
- `python -m pytest tests/unit -q` — 160 passed
- `ruff check server/tools/__init__.py server/subagents/ server/orchestrator/tool_dispatch.py` — clean

**Follow-ups:**
- Step 10: Proactive notifier

---

## 2026-05-22 - requirements sync (fetch tools)

**Scope:** deploy

- `requirements.txt` aligned with `pyproject.toml` (`tavily-python`, `trafilatura`, `scrapling[fetchers]`, `spacy`).
