# Vayumi Server 2 — Build Tracker & Architecture Flows

> **Purpose:** One file to see (1) what's built, (2) how data moves through the system.  
> Updated after each step completes.  
> Config rule: keep `.env` for secrets, deployment endpoints, local paths, ports, and overrides; keep ordinary defaults in `server/config.py`.
> **Last updated:** 2026-06-07 — Step 10 complete + post-Step-10 main-agent amendments (see below)

---

## PLAN.md v1.7 contracts (backfill status)

| Contract | API / behavior | Owned by step | Code status |
|---|---|---|---|
| Session singleton | `enforce_session_singleton(user_id, new_ws)` | Step 1 → Step 6 | ✅ |
| Echo suppression | `begin_tts_with_echo_suppression(turn_id)` | Step 3 → Step 6 | ✅ |
| respond_via table | `compute_respond_via(session_state, input_kind)` | Step 6 | ✅ |
| `chat_message` vs `caption` | §5.5 two-channel delivery | Step 6 | ✅ |
| Streaming TTS | `StreamingTtsPipeline` — sentence → PCM during LLM | Step 6 | ✅ |
| `hello.capabilities.tts` | client declares speaker | Step 4 + Step 6 | ✅ |
| Proactive respond_via | `build_synthetic_turn` + `input_kind='proactive'` | Step 10 | ✅ |

**Current build step:** Step 11 (LanceDB retrieval).

---

## Post-Step-10 amendments (main agent — implemented 2026-06)

These changes are **not** a new roadmap step; they supersede parts of Step 7’s original “DELEGATE-only main tools” wording. See PLAN.md §7.10.1.

### Main turn flow (current)

```
User message (voice STT or typed chat)
        │
        ▼
build_main_chat_messages()
  system = prompts/main.txt (static)
  user   = session context (today's date, warm, task board, injections)
  user   = real user message (last)
        │
        ▼
complete_chat(tools=[web_search, memory_save, memory_recall])
        │
        ├── tool_calls? ──▶ run_native_tool_calls
        │                      │
        │                      ▼
        │                 speak_web_search_results()  (snippets, not LLM guess)
        │                      │
        │                      ▼
        │                 revoice_final if streaming spoke bad partials
        │
        └── prose only? ──▶ parse [DELEGATE]/[REMEMBER]/[RECALL]
                              │
                              ├── [DELEGATE capability=main] → tool_dispatch (fallback)
                              ├── model-output safety nets (tool_fallback.py):
                              │     ack-only, [web_search leak], ungrounded $, stale years
                              │     → emergency web_search + speak snippets
                              └── [DELEGATE capability=research|…] → spawn sub-agent
        │
        ▼
caption + chat_message + TTS (respond_via per Rule 13)
```

**Explicitly removed:** `main_core.txt` / `main_tools.txt` split, user-message keyword routing, search-before-LLM intent heuristics.

### Typed chat while speaking

| Piece | Role |
|---|---|
| `chat_should_queue()` | Queue when busy, playback active, or within 3s post-TTS grace |
| `chat_queue.py` | Depth-1 queue; `start_background_chat_compute` runs `run_turn` during TTS |
| `try_deliver_pending_chat` | Speaks precomputed answer when playback idle |
| `is_trivial_chat_followup` | `?` / `!` do not replace an in-flight queued question |

### Key files (amendments)

| File | Role |
|---|---|
| `server/engine/prompt.py` | `build_main_chat_messages`, `today_context_line()` |
| `server/engine/pool.py` | `complete_chat`, `ChatCompletionResult`, `ParsedToolCall` |
| `server/tools/openai_schema.py` | OpenAI tool schemas for main native tools |
| `server/orchestrator/tool_fallback.py` | Model-output safety nets only |
| `server/orchestrator/tool_dispatch.py` | `run_native_tool_calls`, `speak_web_search_results` |
| `server/orchestrator/prose.py` | Sanitize spoken output (no markdown/URLs/leaks) |
| `server/transport/session_busy.py` | `playback_blocks_voice`, `chat_should_queue` |
| `prompts/main.txt` | Single unified main prompt (tools + DELEGATE research) |

### Step index (quick reference)

| Step | Name | Status | Detail doc |
|------|------|--------|------------|
| 1 | Scaffold + WS echo | ✅ | [step-01.md](step-01.md) |
| 2 | Engine plane | ✅ | [step-02.md](step-02.md) |
| 3 | Voice (STT/TTS/interrupt) | ✅ | [step-03.md](step-03.md) |
| 4 | Web client v1 | ✅ | [step-04.md](step-04.md) |
| 5 | Memory v1 | ✅ | [step-05.md](step-05.md) |
| 6 | v1.7 backfill | ✅ | [step-06.md](step-06.md) |
| 7 | Tool plane | ✅ | [step-07.md](step-07.md) |
| 8 | Sub-agent worker | ✅ | [step-08.md](step-08.md) |
| 9 | Capability bundles | ✅ | [step-09.md](step-09.md) |
| 10 | Proactive notifier | ✅ | [step-10.md](step-10.md) |
| 11 | LanceDB retrieval | ⬜ | [step-11.md](step-11.md) |
| 12–21 | Summarizer, modes, clients… | ⬜ | [roadmap.md](roadmap.md) |

---

## Build Progress

```
PHASE 1 — SPINE                                            PHASE 2 — MULTI-AGENT
┌─────────┬─────────┬─────────┬─────────┬─────────┬─────────┬─────────┐  ┌─────────┬─────────┬─────────┬─────────┬─────────┐
│ Step 1  │ Step 2  │ Step 3  │ Step 4  │ Step 5  │ Step 6  │ Step 7  │  │ Step 8  │ Step 9  │ Step 10 │ Step 11 │ Step 12 │
│Scaffold │ Engine  │ Voice   │ Client  │ Memory  │Backfill │ Tools   │  │SubAgent │Capabil. │Notifier │Retrieval│Summariz.│
│  ✅     │  ✅     │  ✅     │  ✅     │  ✅     │  ✅     │  ✅     │  │  ✅     │  ✅     │  ✅     │  ⬜     │  ⬜     │
└─────────┴────┬────┴────┬────┴────┬────┴────┬────┴────┬────┴────┬────┘  └────┬────┴────┬────┴────┬────┴────┬────┴────┬────┘
               │         │         │         │         │         │            │         │         │         │         │
               ▼         ▼         ▼         ▼         ▼         ▼            ▼         ▼         ▼         ▼         ▼

PHASE 3 — MODES & POLISH                         PHASE 4 — CLIENTS & DEPLOY
┌─────────┬─────────┬─────────┬─────────┬─────────┐  ┌─────────┬─────────┬─────────┬─────────┐
│ Step 13 │ Step 14 │ Step 15 │ Step 16 │ Step 17 │  │ Step 18 │ Step 19 │ Step 20 │ Step 21 │
│Meeting  │Local STT│WakeEcho │Uploads  │  MCP    │  │ Mobile  │ ESP32   │Hardening│Observ.  │
│  ⬜     │  ⬜     │  ⬜     │  ⬜     │  ⬜     │  │  ⬜     │  ⬜     │  ⬜     │  ⬜     │
└─────────┴─────────┴─────────┴─────────┴─────────┘  └─────────┴─────────┴─────────┴─────────┘

Legend: ✅ done   🔄 in progress   ⬜ not started   ❌ blocked

Completed: 10 / 21    Phase 1: 7/7    Phase 2: 3/5    Phase 3: 0/5    Phase 4: 0/4
```

---

## Completed steps (detail sections)

Sections below describe what each finished step added. **Steps 1–10 are complete**; Step 11 is next.

---

## What Step 10 Built

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                    PROACTIVE NOTIFIER (Step 10)                                 │
│                                                                                 │
│  server/orchestrator/notifier.py                                                │
│  ┌───────────────────────────────────────────────────────────────────────────┐  │
│  │ ProactiveNotifier — 3s tick loop over active UserSessions                 │  │
│  │ maybe_surface_signal() — idle, importance, debounce, client_state gates   │  │
│  │ build_synthetic_turn() — compute_respond_via(proactive) → handle_turn path  │  │
│  │ notification toast when visible=false (push stub)                          │  │
│  └───────────────────────────────────────────────────────────────────────────┘  │
│                                                                                 │
│  turn_coordinator.run_supervisor_text_turn() — shared chat + proactive delivery │
│  Removed background_notify.py interim hack                                      │
│  protocol.py — notification message type                                        │
│  web-client — notification toast UI                                             │
└─────────────────────────────────────────────────────────────────────────────────┘
```

### Proactive flow (Step 10)

```
Sub-agent report(DONE|NEEDS_INFO|ERROR)
     │
     ▼
SignalBus → TaskBoard + pending queue
     │
     ▼ (user idle, gates pass)
ProactiveNotifier tick (~3s)
     │
     ├── compute_respond_via(session, 'proactive')
     ├── build_synthetic_turn → run_supervisor_text_turn
     └── caption + chat_message (+ TTS if voice_and_chat)
```

---

## What Step 9 Built

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                    CAPABILITY BUNDLES (Step 9)                                  │
│                                                                                 │
│  server/subagents/capabilities/                                                 │
│  ┌───────────────────────────────────────────────────────────────────────────┐  │
│  │ bundle.py — CapabilityBundle                                              │  │
│  │ load_capability() / render_tool_cards() / resolve_tool_entries()          │  │
│  │ research | productivity | comms manifests (allowed_tools + prompt paths)  │  │
│  └───────────────────────────────────────────────────────────────────────────┘  │
│                                                                                 │
│  server/tools/ summarize_url (extract) · fetch_html (raw) · deep_search       │
│  worker.py — injects tool cards into build_subagent_prompt()                  │
│  tool_dispatch.py — bundle-gated run_subagent_tool_delegate()                   │
│  prompts/sub/{research,productivity,comms}.txt                                │
└─────────────────────────────────────────────────────────────────────────────────┘
```

---

## What Step 7 Built (+ §7.10.1 amendments)

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                         TOOL PLANE (Step 7 + amendments)                        │
│                                                                                 │
│  server/tools/                                                                  │
│  ┌───────────────────────────────────────────────────────────────────────────┐  │
│  │ registry.py — ToolEntry, ToolResult, ToolRegistry, validate_tool_args      │  │
│  │ runner.py — ToolRunner.execute (gate, timeout, events, confirmation)       │  │
│  │ tool_search.py / web_search.py / memory_save.py / memory_recall.py         │  │
│  │ openai_schema.py — native tool schemas for complete_chat                   │  │
│  └───────────────────────────────────────────────────────────────────────────┘  │
│                                                                                 │
│  complete_chat + run_native_tool_calls + speak_web_search_results (snippets)   │
│  tool_fallback.py — model-output safety nets (no keyword routing)              │
│  prose.py — sanitize spoken output (no markdown / [web_search] leaks)        │
│  [DELEGATE capability=main] — fallback when model emits directive text         │
│  ws.py — tool_started / tool_done events on activity feed                        │
│  app.py — init_tools() at boot; Tavily when TAVILY_API_KEY set                   │
└─────────────────────────────────────────────────────────────────────────────────┘
```

### Main tool turn flow (Step 7 + §7.10.1 amendments)

```
User message
     │
     ▼
Supervisor.run_turn — complete_chat (native tool_calls)
     │
     ├── tool_calls → run_native_tool_calls → speak_web_search_results
     │                (short status caption while searching; revoice_final if needed)
     │
     └── prose → [DELEGATE capability=main] fallback OR sub-agent spawn
                 + tool_fallback safety nets on bad model output
     │
     ▼
caption + chat_message (+ voice per respond_via)
```

---

## What Step 8 Built

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                    SUB-AGENT PLANE (Step 8)                                     │
│                                                                                 │
│  server/subagents/                                                              │
│  ┌───────────────────────────────────────────────────────────────────────────┐  │
│  │ report.py — ReportSignal, [REPORT kind=STEP|NEEDS_INFO|DONE|ERROR]         │  │
│  │ worker.py — SubAgentWorker.run / resume_with / pause (no transport)        │  │
│  └───────────────────────────────────────────────────────────────────────────┘  │
│                                                                                 │
│  server/orchestrator/                                                           │
│  ┌───────────────────────────────────────────────────────────────────────────┐  │
│  │ signal_bus.py — publish → TaskBoard + PG audit + task_* WS events          │  │
│  │ task_board.py — render_for_main(), snapshot() for welcome                  │  │
│  │ supervisor.py — spawn_subagent, apply_answer_to_task, cancel_task          │  │
│  │ directives.py — [ANSWER_TO], [STOP_TASK]                                   │  │
│  │ tool_dispatch.py — research DELEGATE → spawn (main unchanged)            │  │
│  └───────────────────────────────────────────────────────────────────────────┘  │
│                                                                                 │
│  engine/pool.py — assign_slot (1–3), submit_assigned, free_slot                │
│  db/schema.sql — tasks, signals tables                                         │
└─────────────────────────────────────────────────────────────────────────────────┘
```

### Background task flow (Step 8)

```
Main [DELEGATE capability=research ...]
     │
     ▼
spawn_subagent → asyncio task + P1 slot
     │
     ├── event task_step (Path A — activity feed only)
     │
     ▼
SubAgentWorker → ToolRunner (capability tools) → report(STEP|DONE|NEEDS_INFO)
     │
     ▼
SignalBus → TaskBoard → (optional) Main reads board on status question
```

---

## What Step 6 Built

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                    v1.7 CONTRACT BACKFILL (Step 6)                              │
│                                                                                 │
│  session_registry.py — user_id → UserSession (Supervisor + interrupt + CC)   │
│  enforce_session_singleton() — supersede old WS (4001), welcome{resumed:true}  │
│                                                                                 │
│  respond_via.py — compute_respond_via() per Rule 13                            │
│  echo_suppression.py — begin_tts_with_echo_suppression() per Rule 12           │
│  delivery.py — caption + chat_message; batch TTS fallback                      │
│  streaming_tts.py + sentence_buffer.py — LLM sentence → TTS PCM (§5.5)         │
│                                                                                 │
│  ws.py — hello-first handshake; chat/voice share delivery + on_token pipeline  │
│  client.js — chat_message bubbles, tts:true, stop/start_capture                │
└─────────────────────────────────────────────────────────────────────────────────┘
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
│  │ retrieval.py — stub (step 11)                                            │  │
│  └───────────────────────────────────────────────────────────────────────────┘  │
│                                                                                 │
│  server/orchestrator/                                                           │
│  ┌───────────────────────────────────────────────────────────────────────────┐  │
│  │ supervisor.py — handle_turn / run_turn + warm + history → Main         │  │
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

*(Step 6 extended this path with `respond_via`, `chat_message`, echo suppression, and session singleton — see above.)*

---

## What Step 3 Built

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                         VOICE PLANE (STT + TTS + INTERRUPT)                   │
│                                                                                 │
│  server/voice/                                                                  │
│  ┌───────────────────────────────────────────────────────────────────────────┐  │
│  │ stt/groq.py — Groq Whisper (utterance → transcript)                     │  │
│  │ tts/kokoro.py — sentence-streamed PCM @ 16 kHz                            │  │
│  │ vad/silero.py — server-side VAD surface                                   │  │
│  │ interrupt.py — InterruptController FSM                                    │  │
│  │ turn.py — audio_end → STT → supervisor → captions + TTS                 │  │
│  └───────────────────────────────────────────────────────────────────────────┘  │
│                                                                                 │
│  Mic PCM → STT → Main (P0) → caption stream + server audio_start/end + PCM    │
│  Interrupt cancels Main decode + TTS only (background work untouched)          │
└─────────────────────────────────────────────────────────────────────────────────┘
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

## Architecture Flow: WebSocket session (current — through Step 6)

```
 Client                                              Server 2
   │                                                      │
   │  WS connect ?token=jwt                               │
   │─────────────────────────────────────────────────────▶│ verify_token → accept
   │                                                      │
   │  hello { client, capabilities:{tts,aec,...}, session_id? }
   │─────────────────────────────────────────────────────▶│ enforce_session_singleton(user_id)
   │                                                      │  (supersede old WS → 4001 if needed)
   │  welcome { session_id, resumed, task_board_snapshot? }
   │◀─────────────────────────────────────────────────────│
   │                                                      │
   │  client_state { playback, capture, visible, route }  │  (on every UI/audio change)
   │─────────────────────────────────────────────────────▶│
   │                                                      │
   │  chat { text }  OR  audio_start → PCM → audio_end    │
   │─────────────────────────────────────────────────────▶│ compute_respond_via → handle_turn
   │                                                      │
   │◀ caption (streaming) + chat_message (final)          │
   │◀ client_control stop_capture → audio_start → PCM     │  (if voice_and_chat)
   │◀ audio_end → client_control start_capture (delay)    │
   │                                                      │
   │  interrupt { source }                                │
   │─────────────────────────────────────────────────────▶│ cancel TTS/Main; chat_message partial

─── JSON    ═══ binary PCM
```

*(Step 1 used echo + welcome-before-hello; that path was replaced in Steps 2–6.)*

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
│ TRANSPORT PLANE  (server/transport/)                         ✅ steps 1, 4, 6       │
│  ws.py, session_registry.py, client_control.py, protocol.py (chat_message, etc.)  │
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
│ ✅ interrupt.py        │  │ ✅ notifier.py           │  │    4 slots, P0/P1/P2 │
│ ✅ respond_via.py      │  │ ░░ task_board.py         │  │ ✅ prompt.py + warm  │
│ ✅ echo_suppression.py │  │ steps 7–10               │  │ ✅ step 2            │
│ ✅ delivery.py         │  │                          │  │                      │
│ ✅ turn → supervisor   │  │                          │  │                      │
│ steps 3, 6             │  │                          │  │                      │
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
│    productivity/         │  │ ✅ registry/runner     │  │ ░░ summarizer.py       │
│ ✅ web_search (Tavily) │  │                        │
│    comms/                │  │                        │  │ ✅ embeddings.py       │
│ steps 8-9               │  │ step 7                 │  │ step 5 ✅, 11-12       │
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

## Audio Flow: Voice + typed chat turn (current — Steps 3–6)

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
  compute_respond_via → voice_and_chat | chat_only
           │
           ▼
  ┌──────────────────┐          ┌────────────────────────────┐
  │ begin_tts_with_  │          │ directives.py              │
  │ echo_suppression │          │ [REMEMBER]/[RECALL]/         │
  │ stop_capture →   │          │ [RESPOND_VIA] override       │
  │ TTS → start_cap  │          └────────────────────────────┘
  └────────┬─────────┘
           ▼
  caption (stream) + chat_message (final) + optional PCM

  Target: ~1.0s to first audio frame
```

---

## Sub-Agent Flow (target — steps 8-10)

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
│   ├── step-06.md              ✅ v1.7 backfill
│   ├── step-07.md              ✅ tool plane
│   ├── step-08.md              ✅ complete (sub-agent worker)
│   ├── step-09.md              ✅ capability bundles
│   ├── step-10.md              ✅ proactive notifier
│   ├── step-11.md              ⬜ pending (LanceDB retrieval)
│   ├── tracker.md              ✅ this file — progress + architecture flows
│   ├── roadmap.md              ✅ full 21-step overview
│   └── history.md              ✅ change log
├── prompts/
│   └── main.txt                ✅ Unified main prompt (native tools + DELEGATE research)
├── server/
│   ├── __init__.py             ✅
│   ├── app.py                  ✅ FastAPI + lifespan + engine + voice + tools boot
│   ├── config.py               ✅ Settings + tavily_api_key + voice defaults
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
│   │   └── prompt.py           ✅ build_main_chat_messages + today_context_line
│   ├── memory/
│   │   ├── __init__.py         ✅
│   │   ├── embeddings.py       ✅ bge-small-en-v1.5 embedder
│   │   ├── facts.py            ✅ versioned fact CRUD + LanceDB upsert
│   │   ├── warm.py             ✅ warm profile + dirty flag + Redis cache
│   │   ├── session.py          ✅ session + turn history
│   │   └── retrieval.py        ✅ stub (step 11)
│   ├── orchestrator/
│   │   ├── __init__.py         ✅
│   │   ├── directives.py       ✅ REMEMBER / RECALL / DELEGATE / RESPOND_VIA
│   │   ├── notifier.py         ✅ proactive synthetic turns (Step 10)
│   │   ├── tool_dispatch.py    ✅ native tool_calls + DELEGATE dispatch
│   │   ├── tool_fallback.py    ✅ model-output safety nets (no keyword routing)
│   │   ├── prose.py            ✅ spoken-output sanitization
│   │   └── supervisor.py       ✅ complete_chat turn + spawn sub-agents
│   ├── subagents/
│   │   ├── worker.py           ✅ CapabilityBundle + tool cards in prompt
│   │   ├── report.py           ✅
│   │   └── capabilities/       ✅ research, productivity, comms manifests
│   ├── tools/
│   │   ├── __init__.py         ✅ multi-capability registry
│   │   ├── registry.py         ✅ ToolEntry / ToolResult / ToolRegistry
│   │   ├── runner.py           ✅ ToolRunner + confirmation stubs
│   │   ├── tool_search.py      ✅ discovery
│   │   ├── web_search.py       ✅ Tavily + DDG fallback
│   │   ├── deep_search.py      ✅ search + per-link fetch
│   │   ├── summarize_url.py    ✅ trafilatura extract
│   │   ├── fetch_html.py       ✅ raw HTML
│   │   ├── memory_save.py      ✅
│   │   ├── memory_recall.py    ✅
│   │   └── openai_schema.py    ✅ native tool schemas for complete_chat
│   ├── voice/
│   │   ├── stt/groq.py         ✅ Groq Whisper STT
│   │   ├── tts/kokoro.py         ✅ Kokoro streaming TTS
│   │   ├── vad/silero.py         ✅ Silero VAD
│   │   ├── interrupt.py        ✅ interrupt FSM
│   │   ├── respond_via.py      ✅ Rule 13 decision table
│   │   ├── echo_suppression.py ✅ Rule 12 TTS path
│   │   ├── delivery.py         ✅ caption + chat_message + TTS
│   │   ├── streaming_tts.py    ✅ PLAN §5.5 interleaved LLM→TTS
│   │   ├── sentence_buffer.py  ✅ sentence boundaries from tokens
│   │   ├── tts_stream.py       ✅ batch sentence PCM (fallback)
│   │   ├── turn.py             ✅ voice turn → delivery
│   │   └── boot.py             ✅ voice plane init
│   └── transport/
│       ├── __init__.py         ✅
│       ├── ws.py               ✅ hello-first, chat/voice, singleton
│       ├── session_registry.py ✅ enforce_session_singleton
│       ├── chat_queue.py       ✅ queue + background compute + pending delivery
│       ├── session_busy.py     ✅ playback grace + chat_should_queue
│       ├── turn_coordinator.py ✅ shared delivery + revoice_final
│       ├── protocol.py         ✅ chat_message, welcome.resumed, events
│       └── client_control.py   ✅ stop/start_capture + playback
├── web-client/
│   ├── index.html              ✅ conversation UI
│   ├── style.css               ✅ styles
│   └── client.js               ✅ mic, chat_message, tool activity pills
└── tests/
    ├── __init__.py             ✅
    ├── conftest.py             ✅ fixtures + fake JWT helper
    └── unit/                   ✅ 217 unit tests (Step 10 + amendments)
        ├── test_protocol.py
        ├── test_respond_via.py
        ├── test_session_singleton.py
        ├── test_client_control.py
        ├── test_voice_*.py
        ├── test_memory_*.py
        ├── test_directives.py
        ├── test_directives_tools.py
        ├── test_supervisor.py
        ├── test_supervisor_tools.py
        ├── test_tools_*.py
        ├── test_tool_dispatch.py
        ├── test_tool_fallback.py
        ├── test_main_chat_messages.py
        ├── test_prose.py
        ├── test_supervisor_no_coerce.py
        ├── test_sentence_buffer.py
        ├── test_streaming_tts.py
        ├── test_notifier.py
        └── test_engine_*.py
```
