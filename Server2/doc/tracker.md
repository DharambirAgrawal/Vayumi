# Vayumi Server 2 — Build Tracker & Architecture Flows

> **Purpose:** One file to see (1) what's built, (2) how data moves through the system.  
> Updated after each step completes.  
> Config rule: keep `.env` for secrets, deployment endpoints, local paths, ports, and overrides; keep ordinary defaults in `server/config.py`.
> **Last updated:** 2026-05-17 — Step 5 complete

---

## Build Progress

```
PHASE 1 — SPINE                                            PHASE 2 — MULTI-AGENT
┌─────────┬─────────┬─────────┬─────────┬─────────┬─────────┐  ┌─────────┬─────────┬─────────┬─────────┬─────────┐
│ Step 1  │ Step 2  │ Step 3  │ Step 4  │ Step 5  │ Step 6  │  │ Step 7  │ Step 8  │ Step 9  │ Step 10 │ Step 11 │
│Scaffold │ Engine  │ Voice   │ Client  │ Memory  │ Tools   │  │SubAgent │Capabil. │Notifier │Retrieval│Summariz.│
│  ✅     │  ✅     │  ✅     │  ✅     │  ✅     │  ⬜     │  │  ⬜     │  ⬜     │  ⬜     │  ⬜     │  ⬜     │
└─────────┴────┬────┴────┬────┴────┬────┴────┬────┴────┬────┘  └────┬────┴────┬────┴────┬────┴────┬────┴────┬────┘
               │         │         │         │         │            │         │         │         │         │
               ▼         ▼         ▼         ▼         ▼            ▼         ▼         ▼         ▼         ▼

PHASE 3 — MODES & POLISH                         PHASE 4 — CLIENTS & DEPLOY
┌─────────┬─────────┬─────────┬─────────┬─────────┐  ┌─────────┬─────────┬─────────┬─────────┐
│ Step 12 │ Step 13 │ Step 14 │ Step 15 │ Step 16 │  │ Step 17 │ Step 18 │ Step 19 │ Step 20 │
│Meeting  │Local STT│WakeEcho │Uploads  │  MCP    │  │ Mobile  │ ESP32   │Hardening│Observ.  │
│  ⬜     │  ⬜     │  ⬜     │  ⬜     │  ⬜     │  │  ⬜     │  ⬜     │  ⬜     │  ⬜     │
└─────────┴─────────┴─────────┴─────────┴─────────┘  └─────────┴─────────┴─────────┴─────────┘

Legend: ✅ done   🔄 in progress   ⬜ not started   ❌ blocked

Completed: 5 / 20    Phase 1: 5/6    Phase 2: 0/5    Phase 3: 0/5    Phase 4: 0/4
```

---

## What Step 5 Built

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                         MEMORY v1 + SUPERVISOR TURNS                            │
│                                                                                 │
│  server/memory/                                                                 │
│  ┌───────────────────────────────────────────────────────────────────────────┐  │
│  │ facts.py — set_fact / get_fact / get_chain (Postgres versioned)          │  │
│  │ warm.py — build_warm_profile, mark_dirty, Redis warm_cache TTL           │  │
│  │ session.py — load_or_create_session, append_turn, recent_turns           │  │
│  │ embeddings.py — bge-small-en-v1.5 (sentence-transformers)                │  │
│  │ retrieval.py — stub (step 10)                                            │  │
│  └───────────────────────────────────────────────────────────────────────────┘  │
│                                                                                 │
│  server/orchestrator/                                                           │
│  ┌───────────────────────────────────────────────────────────────────────────┐  │
│  │ supervisor.py — run_turn: warm + history → Main → directives             │  │
│  │ directives.py — [REMEMBER] / [RECALL] / [RECALL chain]                   │  │
│  └───────────────────────────────────────────────────────────────────────────┘  │
│                                                                                 │
│  server/db/schema.sql — facts, sessions, turns                                  │
│  LanceDB facts_index — embedding per active fact                                │
│  Chat + voice paths route through Supervisor                                    │
└─────────────────────────────────────────────────────────────────────────────────┘
```

### Memory turn flow (Step 5)

```
 User message (chat or voice transcript)
        │
        ▼
 Supervisor.run_turn
        │
        ├── build_warm_profile(user_id)  ← Postgres facts + Redis cache
        ├── recent_turns(session_id)
        ├── append_turn(user)
        │
        ▼
 build_main_prompt(warm + history + user)
        │
        ▼
 Engine P0 slot 0 → stream captions
        │
        ▼
 parse_directives → set_fact / get_fact / get_chain
        │
        ├── [RECALL] → follow-up completion with [RECALL_RESULT …]
        └── strip_directives → final caption + TTS (voice)
```

---

## What Step 4 Built

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                         WEB CLIENT + CLIENT CONTROL                             │
│                                                                                 │
│  web-client/                                                                    │
│  ┌───────────────────────────────────────────────────────────────────────────┐  │
│  │ index.html + style.css — conversation UI (captions, chat, activity)      │  │
│  │ client.js — toggle mic, TTS queue, client_state / client_control         │  │
│  └───────────────────────────────────────────────────────────────────────────┘  │
│                                                                                 │
│  server/transport/client_control.py                                             │
│  ┌───────────────────────────────────────────────────────────────────────────┐  │
│  │ ClientControlSession — tracks playback/capture/visibility/route          │  │
│  │ send_client_control() — play/stop/clear_queue/duck/unduck/capture        │  │
│  │ interrupt → stop + clear_queue; TTS audio_start → play                   │  │
│  └───────────────────────────────────────────────────────────────────────────┘  │
│                                                                                 │
│  protocol.py — client_state, mode (client→server); client_control, event       │
└─────────────────────────────────────────────────────────────────────────────────┘
```

### Audio control handshake (Step 4)

```
 Server                              Web Client
   │                                      │
   │── client_control {stop,clear_queue} ─▶│  (on interrupt)
   │◀──────── client_state {playback:idle} ─│
   │                                      │
   │── audio_start + client_control play ─▶│  (TTS begins)
   │── binary PCM frames ─────────────────▶│
   │◀──────── client_state {playing} ─────│
   │── audio_end ─────────────────────────▶│
   │◀──────── client_state {idle} ──────────│
```

---

## What Step 2 Built

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                              ENGINE PLANE                                       │
│                                                                                 │
│  server/engine/runner.py                                                        │
│  ┌───────────────────────────────────────────────────────────────────────────┐  │
│  │ start_llama_server() → /opt/homebrew/bin/llama-server                    │  │
│  │ flags: -m model.gguf --port 8081 -np 4 --ctx-size 32768 -sps 0.5         │  │
│  │ health_check() polls /health until ready                                  │  │
│  │ stop_llama_server() terminates the subprocess on app shutdown             │  │
│  └───────────────────────────────────────────────────────────────────────────┘  │
│                                                                                 │
│  server/engine/pool.py                                                          │
│  ┌───────────────────────────────────────────────────────────────────────────┐  │
│  │ CompletionPriority: P0 Main, P1 sub-agent, P2 summarizer                  │  │
│  │ submit(request, priority, slot_hint=0) → CompletionHandle                 │  │
│  │ dispatcher streams llama-server tokens back to transport                  │  │
│  │ slot 0 is used for Main; slots 1-3 are ready for later steps              │  │
│  └───────────────────────────────────────────────────────────────────────────┘  │
│                                                                                 │
│  Chat path: WS chat → build_main_prompt() → engine pool P0 slot 0 → caption     │
└─────────────────────────────────────────────────────────────────────────────────┘
```

---

## What Step 1 Built

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                              server/app.py                                      │
│                          FastAPI + lifespan boot                                │
│                                                                                 │
│  Startup sequence:                                                              │
│  ┌──────────┐   ┌──────────┐   ┌──────────┐   ┌──────────────┐                │
│  │ Postgres  │──▶│  Redis   │──▶│ LanceDB  │──▶│ server_health│                │
│  │  pool     │   │  client  │   │  connect  │   │  last_boot   │                │
│  └──────────┘   └──────────┘   └──────────┘   └──────────────┘                │
│                                                                                 │
│  Routes:                                                                        │
│  GET  /              → web-client/index.html (static)                          │
│  WS   /ws/v1/session → transport/ws.py (echo)                                 │
└─────────────────────────────────────────────────────────────────────────────────┘
```

---

## Architecture Flow: How a WebSocket Session Works (Step 1)

```
 ┌──────────────┐                          ┌──────────────────────────────────────┐
 │  Web Client  │                          │           Server 2                   │
 │  (browser)   │                          │                                      │
 └──────┬───────┘                          └──────────────────┬───────────────────┘
        │                                                     │
        │  1. WS connect: /ws/v1/session?token=dev            │
        │────────────────────────────────────────────────────▶│
        │                                                     │
        │                            ┌────────────────────────┤
        │                            │  auth.py               │
        │                            │  verify_token("dev")   │
        │                            │  → TokenPayload        │
        │                            │    user_id: dev_user   │
        │                            │    session_id: dev_ses  │
        │                            └────────────────────────┤
        │                                                     │
        │  2. welcome { session_id, server_version }          │
        │◀────────────────────────────────────────────────────│
        │                                                     │
        │  3. hello { client:"web", capabilities:{...} }      │
        │────────────────────────────────────────────────────▶│
        │                                                     │
        │  4. echo { kind:"hello", payload:{...} }            │
        │◀────────────────────────────────────────────────────│
        │                                                     │
        │  5. chat { text: "hello" }                          │
        │────────────────────────────────────────────────────▶│
        │                                                     │
        │  6. echo { kind:"chat", payload: {text:"hello"} }   │
        │◀────────────────────────────────────────────────────│
        │                                                     │
        │  7. audio_start { sample_rate:16000 }               │
        │────────────────────────────────────────────────────▶│
        │                                                     │
        │  8. [binary PCM frames]                             │
        │════════════════════════════════════════════════════▶│
        │                                                     │
        │  9. [binary PCM frames echoed back]                 │
        │◀════════════════════════════════════════════════════│
        │                                                     │
        │  10. audio_end {}                                   │
        │────────────────────────────────────────────────────▶│
        │                                                     │
        │  11. echo { kind:"audio_end" }                      │
        │◀────────────────────────────────────────────────────│
        │                                                     │
        │  12. ping { t: 1234567890 }                         │
        │────────────────────────────────────────────────────▶│
        │                                                     │
        │  13. pong { t: 1234567890 }                         │
        │◀────────────────────────────────────────────────────│
        │                                                     │

─── = JSON text frame
═══ = binary PCM frame
```

---

## Architecture Flow: Auth Decision Tree

```
                        verify_token(token)
                              │
                    ┌─────────┴──────────┐
                    │                    │
              APP_ENV=dev          APP_ENV=prod
              JWT_PUBLIC_KEY       (or dev + key set)
              not set                    │
                    │              ┌─────┴──────┐
                    │              │ jose.decode │
                    │              │ RS256       │
             token == "dev"?       └─────┬──────┘
              │         │                │
             yes        no         ┌─────┴──────────┐
              │         │          │ check claims    │
              ▼         ▼          │ sub, sid, jti   │
         TokenPayload  AuthError   └─────┬──────────┘
         (dev_user)    (4401)            │
                                   ┌─────┴──────────┐
                                   │ blocklist check │
                                   │ redis: jti      │
                                   └─────┬──────────┘
                                         │
                                   ┌─────┴──────┐
                                   │            │
                                not blocked   blocked
                                   │            │
                                   ▼            ▼
                              TokenPayload   AuthError
                                             (revoked)
```

---

## Architecture Flow: Boot Sequence

```
uvicorn starts
      │
      ▼
  lifespan(app)
      │
      ├──▶ get_settings()          Load .env → Settings (fail fast if missing)
      │
      ├──▶ setup_logging()         structlog: JSON (prod) or pretty (dev)
      │
      ├──▶ init_postgres()         asyncpg pool (min=2, max=10)
      │    └──▶ CREATE TABLE       server_health (idempotent)
      │    └──▶ UPSERT             last_boot = now()
      │
      ├──▶ init_redis()            PING own Redis
      │
      ├──▶ init_server1_redis()    PING Server 1 Redis (skip if dev + not set)
      │
      ├──▶ init_lancedb()          Open dir, create _ping table if missing
      │
      ├──▶ log "app.ready"         All connections verified
      │
      ▼
  app serves requests
      │
      ▼
  shutdown
      ├──▶ close_lancedb()
      ├──▶ close_redis()
      └──▶ close_postgres()
```

---

## Architecture Flow: Full System (what it will look like)

This is the target. Grey sections are not built yet.

```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                                    CLIENT (web/mobile/ESP32)                           │
│  mic → AudioWorklet → PCM ──────▶ WS binary frames                                   │
│  keyboard ──────────────────────▶ WS JSON { type:"chat" }                             │
│  file ──────────────────────────▶ POST /upload/v1/file → file_id                      │
│  ◀─────── WS JSON (captions, events, notifications)                                  │
│  ◀─────── WS binary (TTS PCM audio)                                                  │
└──────────────────────────────────────────┬─────────────────────────────────────────────┘
                                           │ WebSocket
                                           ▼
┌──────────────────────────────────────────────────────────────────────────────────────┐
│ TRANSPORT PLANE  (server/transport/)                                    ✅ step 1    │
│  ws.py ─── auth handshake ─── inbound/outbound loops ─── protocol.py                │
└──────────────────────────────────────────┬───────────────────────────────────────────┘
                                           │
              ┌────────────────────────────┼────────────────────────────┐
              │                            │                            │
              ▼                            ▼                            ▼
┌─────────────────────────┐  ┌──────────────────────────┐  ┌──────────────────────┐
│ VOICE PLANE             │  │ ORCHESTRATOR PLANE       │  │ ENGINE PLANE         │
│ (server/voice/)         │  │ (server/orchestrator/)   │  │ (server/engine/)     │
│                         │  │                          │  │                      │
│ ✅ STT (Groq)          │  │ ✅ supervisor.py         │  │ ✅ runner.py         │
│ ✅ TTS (Kokoro)        │  │ ✅ directives.py         │  │    llama-server      │
│ ✅ VAD (Silero)        │  │ ░░ signal_bus.py         │  │ ✅ pool.py           │
│ ✅ interrupt.py        │  │ ░░ notifier.py           │  │    4 slots, P0/P1/P2 │
│ ✅ turn → supervisor   │  │ ░░ task_board.py         │  │ ✅ prompt.py + warm  │
│ step 3 ✅, polish s4   │  │ steps 7-9                │  │ ✅ step 2            │
└─────────────────────────┘  └────────────┬─────────────┘  └──────────────────────┘
                                          │
                    ┌─────────────────────┼──────────────────────┐
                    │                     │                      │
                    ▼                     ▼                      ▼
┌──────────────────────────┐  ┌────────────────────────┐  ┌────────────────────────┐
│ SUB-AGENT PLANE          │  │ TOOL PLANE             │  │ MEMORY PLANE           │
│ (server/subagents/)      │  │ (server/tools/)        │  │ (server/memory/)       │
│                          │  │                        │  │                        │
│ ░░ worker.py             │  │ ░░ registry.py         │  │ ✅ facts.py (versioned)│
│ ░░ report.py             │  │ ░░ runner.py           │  │ ✅ warm.py (profile)   │
│ ░░ capabilities/         │  │ ░░ web_search.py       │  │ ░░ retrieval.py (stub) │
│    research/             │  │ ░░ mcp_adapter.py      │  │ ✅ session.py          │
│    productivity/         │  │ ░░ tool_search.py      │  │ ░░ summarizer.py       │
│    comms/                │  │                        │  │ ✅ embeddings.py       │
│ steps 7-8               │  │ step 6                 │  │ step 5 ✅, 10-11       │
└──────────────────────────┘  └────────────────────────┘  └────────────────────────┘
                                                                    │
                                                                    ▼
┌──────────────────────────────────────────────────────────────────────────────────────┐
│ DATA PLANE  (server/db/)                                               ✅ step 1    │
│                                                                                      │
│  ┌─────────────────┐    ┌─────────────────┐    ┌─────────────────────┐              │
│  │   Postgres       │    │     Redis        │    │     LanceDB         │              │
│  │   (Supabase)     │    │   (cloud)        │    │   (local dir)       │              │
│  │                  │    │                  │    │                     │              │
│  │ server_health    │    │ own: signals,    │    │ _ping (health)     │              │
│  │ ✅ facts         │    │ warm_cache       │    │ ✅ facts_index     │              │
│  │ ✅ sessions      │    │ S1: blocklist    │    │    (embeddings)    │              │
│  │ ✅ turns         │    │                  │    │                     │              │
│  │ ░░ tasks         │    │                  │    │                     │              │
│  │ ░░ signals       │    │                  │    │                     │              │
│  └─────────────────┘    └─────────────────┘    └─────────────────────┘              │
│                                                                                      │
│  Note: same Postgres & Redis as Server 1 (shared infra, separate tables)            │
└──────────────────────────────────────────────────────────────────────────────────────┘

Legend: ✅ = built    ░░ = not yet built
```

---

## Audio Flow: Voice Turn (target — steps 2-4)

```
User speaks into mic
        │
        ▼
  ┌──────────────┐      ┌───────────────┐      ┌──────────────┐
  │ AudioWorklet  │─────▶│ WS binary     │─────▶│ VAD (Silero) │
  │ Float32→Int16│      │ PCM frames    │      │ end-of-utt   │
  └──────────────┘      └───────────────┘      └──────┬───────┘
                                                       │
                                                       ▼
                                                ┌──────────────┐
                                                │ STT (Groq)   │
                                                │ audio → text │
                                                └──────┬───────┘
                                                       │ transcript
                                                       ▼
  ┌──────────────────────────────────────────────────────────────┐
  │                    SUPERVISOR                                 │
  │  assemble context: warm profile + history + task board       │
  │  submit to Main Agent (engine slot 0, P0)                    │
  └──────────────────────────────────────────┬───────────────────┘
                                              │
                                              ▼
  ┌──────────────────────────────────────────────────────────────┐
  │               MAIN AGENT (llama-server slot 0)               │
  │  streams text + directives                                    │
  │  plain text → TTS    directives → orchestrator                │
  └─────────────┬───────────────────────────┬────────────────────┘
                │                           │
                ▼                           ▼
  ┌──────────────────┐          ┌────────────────────────────┐
  │ TTS (Kokoro)     │          │ directives.py              │
  │ text → PCM       │          │ [DELEGATE] → spawn sub     │
  │ sentence-stream  │          │ [REMEMBER] → write fact    │
  └────────┬─────────┘          │ [RECALL]   → read fact     │
           │                    │ [STOP_TASK]→ cancel sub    │
           ▼                    └────────────────────────────┘
  ┌──────────────────┐
  │ WS binary out    │
  │ PCM → browser    │
  │ → speaker        │
  └──────────────────┘

  Total target latency: ~1.0s to first audio frame
```

---

## Sub-Agent Flow (target — steps 7-9)

```
Main emits: [DELEGATE capability=research goal="..." payload={...}]
        │
        ▼
  ┌──────────────────────────────────────────────────────────┐
  │ Supervisor.spawn_subagent()                              │
  │  → create task row (Postgres)                            │
  │  → create SubAgentWorker                                 │
  │  → assign engine slot (P1)                               │
  │  → emit event{kind:"tool_started"} to client             │
  └──────────────────────────────────┬───────────────────────┘
                                     │
                                     ▼
  ┌──────────────────────────────────────────────────────────┐
  │ SubAgentWorker.run()                                     │
  │  sees ONLY its capability's tools + goal                 │
  │  loop:                                                    │
  │    model step → [CALL tool_name ...] or report(...)      │
  │    tool call → ToolRunner.execute() → inject result      │
  │    continue until DONE or ERROR                          │
  └──────────────────────────────────┬───────────────────────┘
                                     │
        ┌────────────────────────────┼────────────────────────┐
        │                            │                        │
        ▼                            ▼                        ▼
  report(STEP)                 report(DONE)            report(NEEDS_INFO)
        │                            │                        │
        ▼                            ▼                        ▼
  Signal Bus                   Signal Bus               Signal Bus
        │                            │                        │
        ▼                            ▼                        ▼
  task_board update            task_board update         task_board update
  event → client UI            Notifier checks:         status = paused
  (Main NOT called)            user silent?              Notifier → Main
                               importance high?          Main asks user
                               → synthetic turn          → [ANSWER_TO ...]
                               Main speaks result        → worker resumes
```

---

## File Map (what exists today)

```
Server2/
├── pyproject.toml              ✅ deps + project metadata
├── .env.example                ✅ all env vars documented
├── .env                        ✅ your cloud Postgres + Redis URLs
├── .gitignore                  ✅ Python + models/ + data/
├── docker-compose.dev.yml      ✅ optional local Postgres + Redis (cloud .env typical)
├── PLAN.md                     ✅ frozen architecture
├── doc/
│   ├── step-01.md              ✅ this step
│   ├── step-02.md              ✅ engine plane
│   ├── step-03.md              ✅ voice plane
│   ├── step-04.md              ✅ web client v1
│   ├── step-05.md              ✅ memory v1
│   ├── step-06.md              ⬜ pending
│   ├── tracker.md              ✅ this file — progress + architecture flows
│   ├── roadmap.md              ✅ full 20-step overview
│   └── history.md              ✅ change log
├── prompts/
│   └── main.txt                ✅ Main Agent system prompt
├── server/
│   ├── __init__.py             ✅
│   ├── app.py                  ✅ FastAPI + lifespan + engine + voice boot
│   ├── config.py               ✅ Settings + engine + voice defaults
│   ├── logger.py               ✅ structlog setup
│   ├── auth.py                 ✅ verify_token (dev bypass + RS256 prod)
│   ├── db/
│   │   ├── __init__.py         ✅
│   │   ├── postgres.py         ✅ asyncpg pool + migration
│   │   ├── redis.py            ✅ own Redis + Server 1 Redis, masked logs
│   │   ├── lancedb.py          ✅ connect + writable check + facts_index
│   │   └── schema.sql          ✅ facts, sessions, turns DDL
│   ├── engine/
│   │   ├── __init__.py         ✅
│   │   ├── runner.py           ✅ llama-server subprocess lifecycle
│   │   ├── pool.py             ✅ priority queue + slot manager
│   │   └── prompt.py           ✅ Main prompt assembly + warm/history
│   ├── memory/
│   │   ├── __init__.py         ✅
│   │   ├── embeddings.py       ✅ bge-small-en-v1.5 embedder
│   │   ├── facts.py            ✅ versioned fact CRUD + LanceDB upsert
│   │   ├── warm.py             ✅ warm profile + dirty flag + Redis cache
│   │   ├── session.py          ✅ session + turn history
│   │   └── retrieval.py        ✅ stub (step 10)
│   ├── orchestrator/
│   │   ├── __init__.py         ✅
│   │   ├── directives.py       ✅ REMEMBER / RECALL parsing
│   │   └── supervisor.py       ✅ context assembly + turn lifecycle
│   ├── voice/
│   │   ├── stt/groq.py         ✅ Groq Whisper STT
│   │   ├── tts/kokoro.py       ✅ Kokoro streaming TTS
│   │   ├── vad/silero.py       ✅ Silero VAD
│   │   ├── interrupt.py        ✅ interrupt FSM
│   │   ├── turn.py             ✅ voice turn pipeline
│   │   └── boot.py             ✅ voice plane init
│   └── transport/
│       ├── __init__.py         ✅
│       ├── ws.py               ✅ voice + chat + client_state/mode
│       ├── protocol.py         ✅ client_state, client_control, event
│       └── client_control.py   ✅ server→client playback/capture commands
├── web-client/
│   ├── index.html              ✅ conversation UI
│   ├── style.css               ✅ styles
│   └── client.js               ✅ mic toggle, client_state/control
└── tests/
    ├── __init__.py             ✅
    ├── conftest.py             ✅ fixtures + fake JWT helper
    └── unit/
        ├── test_db_redis.py    ✅ Redis URL log masking
        ├── test_engine_pool.py ✅ engine queue + streaming
        ├── test_engine_prompt.py ✅ Main prompt assembly
        ├── test_engine_runner.py ✅ llama command + health
        ├── test_protocol.py    ✅ protocol round-trips
        ├── test_client_control.py ✅ client control session + send
        ├── test_voice_*.py     ✅ voice plane unit tests
        ├── test_memory_facts.py ✅ fact versioning + chains
        ├── test_memory_warm.py ✅ warm profile build + dirty
        ├── test_directives.py  ✅ REMEMBER/RECALL parse + execute
        └── test_supervisor.py  ✅ turn lifecycle + RECALL follow-up
```
