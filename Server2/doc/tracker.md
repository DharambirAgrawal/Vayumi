# Vayumi Server 2 — Build Tracker & Architecture Flows

> **Purpose:** One file to see (1) what's built, (2) how data moves through the system.  
> Updated after each step completes.  
> **Last updated:** 2026-05-17 — Step 1 complete

---

## Build Progress

```
PHASE 1 — SPINE                                            PHASE 2 — MULTI-AGENT
┌─────────┬─────────┬─────────┬─────────┬─────────┬─────────┐  ┌─────────┬─────────┬─────────┬─────────┬─────────┐
│ Step 1  │ Step 2  │ Step 3  │ Step 4  │ Step 5  │ Step 6  │  │ Step 7  │ Step 8  │ Step 9  │ Step 10 │ Step 11 │
│Scaffold │ Engine  │ Voice   │ Client  │ Memory  │ Tools   │  │SubAgent │Capabil. │Notifier │Retrieval│Summariz.│
│  ✅     │  ⬜     │  ⬜     │  ⬜     │  ⬜     │  ⬜     │  │  ⬜     │  ⬜     │  ⬜     │  ⬜     │  ⬜     │
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

Completed: 1 / 20    Phase 1: 1/6    Phase 2: 0/5    Phase 3: 0/5    Phase 4: 0/4
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
│ ░░ STT (Groq/local)    │  │ ░░ supervisor.py         │  │ ░░ runner.py         │
│ ░░ TTS (Kokoro)        │  │ ░░ directives.py         │  │    llama-server      │
│ ░░ VAD (Silero)        │  │ ░░ signal_bus.py         │  │ ░░ pool.py           │
│ ░░ interrupt.py        │  │ ░░ notifier.py           │  │    4 slots, P0/P1/P2 │
│                         │  │ ░░ task_board.py         │  │ ░░ prompt.py         │
│ steps 3-4              │  │ steps 5-9                │  │ step 2               │
└─────────────────────────┘  └────────────┬─────────────┘  └──────────────────────┘
                                          │
                    ┌─────────────────────┼──────────────────────┐
                    │                     │                      │
                    ▼                     ▼                      ▼
┌──────────────────────────┐  ┌────────────────────────┐  ┌────────────────────────┐
│ SUB-AGENT PLANE          │  │ TOOL PLANE             │  │ MEMORY PLANE           │
│ (server/subagents/)      │  │ (server/tools/)        │  │ (server/memory/)       │
│                          │  │                        │  │                        │
│ ░░ worker.py             │  │ ░░ registry.py         │  │ ░░ facts.py (versioned)│
│ ░░ report.py             │  │ ░░ runner.py           │  │ ░░ warm.py (profile)   │
│ ░░ capabilities/         │  │ ░░ web_search.py       │  │ ░░ retrieval.py        │
│    research/             │  │ ░░ mcp_adapter.py      │  │ ░░ session.py          │
│    productivity/         │  │ ░░ tool_search.py      │  │ ░░ summarizer.py       │
│    comms/                │  │                        │  │                        │
│ steps 7-8               │  │ step 6                 │  │ steps 5, 10-11         │
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
│  │ ░░ facts         │    │      cache       │    │ ░░ facts_index     │              │
│  │ ░░ sessions      │    │ S1: blocklist    │    │    (embeddings)    │              │
│  │ ░░ turns         │    │                  │    │                     │              │
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
├── docker-compose.dev.yml      ✅ local dev option (Postgres + Redis)
├── PLAN.md                     ✅ frozen architecture
├── doc/
│   ├── step-01.md              ✅ this step
│   ├── tracker.md              ✅ this file — progress + architecture flows
│   ├── roadmap.md              ✅ full 20-step overview
│   └── history.md              ✅ change log
├── server/
│   ├── __init__.py             ✅
│   ├── app.py                  ✅ FastAPI + lifespan
│   ├── config.py               ✅ Settings (pydantic-settings)
│   ├── logger.py               ✅ structlog setup
│   ├── auth.py                 ✅ verify_token (dev bypass + RS256 prod)
│   ├── db/
│   │   ├── __init__.py         ✅
│   │   ├── postgres.py         ✅ asyncpg pool + migration
│   │   ├── redis.py            ✅ own Redis + Server 1 Redis
│   │   └── lancedb.py          ✅ connect + writable check
│   └── transport/
│       ├── __init__.py         ✅
│       ├── ws.py               ✅ WS endpoint + echo loop
│       └── protocol.py         ✅ typed message envelopes
├── web-client/
│   ├── index.html              ✅ dev client UI
│   └── client.js               ✅ WS + AudioWorklet + PCM capture
└── tests/
    ├── __init__.py             ✅
    ├── conftest.py             ✅ fixtures + fake JWT helper
    └── unit/
        └── test_protocol.py    ✅ 17 tests (all green)
```
