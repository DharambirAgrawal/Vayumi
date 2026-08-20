# Vayumi

![Python](https://img.shields.io/badge/python-3.11-3776AB?logo=python&logoColor=white)
![TypeScript](https://img.shields.io/badge/typescript-Node%2024-3178C6?logo=typescript&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-WebSocket-009688?logo=fastapi&logoColor=white)
![License](https://img.shields.io/badge/license-Proprietary-lightgrey)

**A voice-first personal AI agent that remembers you, delegates work to sub-agents, and speaks back in real time.**

Vayumi is a two-service backend for a Jarvis-style personal assistant: a live voice conversation loop (STT → LLM → TTS) backed by an orchestrator that can hand off multi-step work to specialized sub-agents, persist facts about the user as versioned memory, and summarize meetings after the fact. This repository is the flagship backend of the Vayumi project. The mobile app, marketing site, and a few other satellite pieces live in separate repos.

---

## Repository layout

This is a monorepo holding **two independent services** that share no code:

| Service | Stack | Role |
|---|---|---|
| **`Server1/`** | Node.js + TypeScript + Express + Drizzle/Postgres | The live REST API the mobile app talks to today: auth, users, settings, reminders, meeting *sync* (device-recorded meetings uploaded with their summary/transcript), push notifications, and a cloud-LLM proxy (Groq → Cerebras → Gemini fail-over) for lightweight AI features in the app. Deployed to Heroku on every push to `main`. |
| **`Server2/`** | Python 3.11 + FastAPI + WebSocket | The voice-first multi-agent engine: speech-to-text, a local LLM via `llama-server`, streaming text-to-speech, an orchestrator that runs tools and delegates to sub-agents, and a layered memory system (versioned facts + semantic recall + session compression), built step by step against a frozen, spec-driven architecture doc. **Not currently hosted**; it's the R&D core of the project and runs locally against your own LLM/Postgres/Redis. |

---

## Features

### Server2: the agent engine (implemented, verified in code)

- **Real-time voice conversation**: Groq Whisper STT, Silero VAD for end-of-utterance detection, and streaming Kokoro TTS, wired together with an interrupt controller (barge-in support) and a full speech state machine (idle / listening / thinking / speaking).
- **Local LLM inference**: a `llama-server` subprocess (Gemma 3n by default) behind a priority-queued engine pool with reserved slots for the main agent, sub-agents, and a background summarizer, so a sub-agent task never starves the live conversation.
- **Layered memory**
  - Versioned key-value facts (`facts` table) with full supersession history, so updating a fact keeps the old value queryable instead of overwriting it.
  - A "warm profile" (~600 tokens: name, city, relationships, preferences, comm style) rebuilt from facts and always injected into the main agent's context.
  - Semantic recall over facts and past sessions via LanceDB + a local `bge-small-en-v1.5` embedder.
  - Automatic session compression once history passes a token threshold, with fact extraction from completed tasks.
- **Agent orchestration**: a main-agent turn loop that calls native tool calls (`web_search`, `memory_save`, `memory_recall`, `tool_search`) directly, and can delegate multi-step work to ephemeral **sub-agents** scoped to a capability bundle (`research`, `productivity`, `comms`), each with its own tool access and its own `report()` protocol (STEP / NEEDS_INFO / DONE / ERROR) tracked on a task board with pause/resume/cancel.
- **Proactive notifier**: a background loop that drains completed sub-agent results while the user is silent and surfaces them as a spoken/typed notification, gated by an importance threshold and a debounce interval.
- **Meeting mode**: a dedicated conversation mode where the main agent goes dormant, utterances are buffered per (best-effort) speaker and chunked into LanceDB, "Hey Vayumi" addresses are still detected mid-meeting, and a background job produces a post-meeting summary stored as a versioned fact.
- **Real tools, honestly scoped**: web search (Tavily, DDG fallback), page fetch/extract, URL summarization (trafilatura), and a "deep search" multi-source tool are functional today. **Outbound email (`send_email`) and workspace drafting (`draft_document`) are implemented as tool stubs**: they detect the missing OAuth/workspace connection and return `user_action_required` instead of actually sending or drafting anything, since those integrations aren't wired up yet.
- **73 test files / 250+ unit tests** covering the orchestrator, memory, voice pipeline, and tool dispatch.

### Server1: the deployed API (implemented, verified in code)

- Email/password + Google + Sign in with Apple auth, RS256 JWT access tokens, opaque refresh tokens tracked (and revocable) in Postgres.
- Reminders with recurrence rules (`rrule`), fired by an in-process cron job and delivered via push (FCM/APNs).
- Meeting *sync*: the client records and analyzes meetings on-device and uploads the resulting summary, key points, action items, and transcript. Audio itself never leaves the device.
- "Life tabs": a flexible, user-defined personal tracker system (timeline/cards/chart/checklist/gallery layouts) synced offline-first from the device.
- A cloud-LLM proxy endpoint used by the mobile app directly, independent of Server2, with per-user daily/per-minute quotas and an allow-list.
- Gmail/Outlook OAuth integration routes exist but are intentionally 501 stubs: dormant code, not wired to anything yet.

---

## Tech stack

**Server2 (agent engine):** Python 3.11, FastAPI, WebSocket transport, `llama-server` (local GGUF inference, Gemma 3n), Groq Whisper (STT), Kokoro (streaming TTS), Silero VAD, `sentence-transformers` / `bge-small-en-v1.5` (embeddings), LanceDB (vector memory), asyncpg + Postgres (facts, sessions, tasks), Redis, Tavily/trafilatura/scrapling (research tools), structlog, pytest.

**Server1 (REST API):** Node 24, TypeScript, Express, Drizzle ORM over `postgres.js`, Supabase (Postgres + file storage), `jose`/`jsonwebtoken` (RS256), `node-cron`, OCI Email Delivery, Firebase Cloud Messaging, Groq/Cerebras/Gemini (cloud LLM fail-over).

---

## How it works

### Server2's seven planes

The agent engine is organized into seven cooperating layers (`server/transport`, `voice`, `engine`, `orchestrator`, `subagents`, `tools`, `memory`):

1. **Transport** (`transport/ws.py`): a single WebSocket endpoint per user (session singleton, where a second connection cleanly supersedes the first), speaking a typed JSON + binary-PCM protocol.
2. **Voice** (`voice/`): turns raw microphone PCM into a transcript (Groq Whisper, chunked via Silero VAD for end-of-utterance detection) and turns the agent's reply back into streamed PCM (Kokoro TTS), with an interrupt/echo-suppression layer so the mic pauses while Vayumi is speaking.
3. **Engine** (`engine/pool.py`): a single `llama-server` process shared across the whole system through a priority queue, where the live conversation (P0) always preempts sub-agent work (P1) and the background summarizer (P2).
4. **Orchestrator** (`orchestrator/supervisor.py`): runs one "turn" at a time by building the prompt (warm profile + recent/compressed history + retrieved memory), getting a completion, executing any native tool calls, parsing fallback directives (`[REMEMBER]`, `[RECALL]`, `[DELEGATE]`, `[ANSWER_TO]`, `[STOP_TASK]`), deciding whether the reply goes out as voice, chat, or both (`respond_via`), and streaming the result back over the transport.
5. **Sub-agents** (`subagents/worker.py`): a `[DELEGATE]` spawns an ephemeral `SubAgentWorker` scoped to one capability bundle (research / productivity / comms), running its own tool-call loop and reporting progress back to the supervisor over an async signal bus; a `TaskBoard` tracks pause/resume/cancel state so a task survives a reconnect.
6. **Tools** (`tools/registry.py`, `tools/runner.py`): a capability-gated registry (`ToolCard`/`ToolEntry`/`ToolResult`) with risk levels (read/write/send/delete/purchase), so a sub-agent only ever sees the tools its capability grants it, and every call is timed, normalized, and audited.
7. **Memory** (`memory/`): Postgres holds versioned facts and session/turn history; LanceDB holds embeddings for semantic recall over facts and meeting chunks; a warm-profile cache in Redis keeps the "who is this user" context cheap to rebuild every turn.

### Server1's request path

`server.ts` boots by verifying the DB, running any pending raw-SQL migrations (advisory-lock guarded, tracked in `__app_migrations`, not via `drizzle-kit migrate`), starting the reminder cron, then listening. `app.ts` wires the Express middleware chain; `routes/index.ts` mounts each domain module (auth, users, settings, meetings, reminders, life, notifications, integrations) under `/api/v1`. Each module is a vertical slice (router → controller → service → validators) talking to Postgres through Drizzle. There is no Redis: rate limiting is an atomic Postgres upsert and the reminder fire-lock is a `pg_advisory_lock`, a deliberate simplification over an earlier Redis-based design.

---

## Getting started

### Server1 (REST API)

```bash
cd Server1
npm install
cp .env.example .env   # fill in your own Postgres/Supabase, JWT keypair, etc.
npm run dev             # tsx watch, runs migrations on boot
```

Required environment variables (see `Server1/.env.example` for the full list): `DATABASE_URL`, an RS256 `JWT_PRIVATE_KEY`/`JWT_PUBLIC_KEY` pair, Supabase storage credentials, and OCI email credentials if you want verification/reset emails to send. Everything else (Google/Apple sign-in, push, cloud-LLM keys) is optional and features degrade gracefully without it.

### Server2 (agent engine)

```bash
cd Server2
python3.11 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
python -m spacy download en_core_web_sm
scrapling install
cp .env.example .env   # fill in DATABASE_URL, REDIS_URL, GROQ_API_KEY, llama-server path
LOG_LEVEL=debug uvicorn server.app:app --port 8080
```

You'll also need a local `llama-server` binary and a GGUF model under `models/` (the default prompt is tuned for Gemma 3n E2B), plus a Groq API key for speech-to-text. `Server2/.env.example` documents every variable; a `docker-compose.dev.yml` is provided if you'd rather run Postgres/Redis locally than point at cloud instances.

---

## Usage

With Server2 running, open `http://localhost:8080`: the bundled reference web client (`web-client/`) connects over WebSocket using the dev token `dev` (real Server1-issued JWTs work too once `JWT_PUBLIC_KEY` is set). From there you can type or talk to Vayumi, watch the activity feed as it calls tools or spins up sub-agents, and switch into meeting mode.

Server1 is a conventional REST API; see `Server1/doc/SERVER1_API_CATALOG.md` for the endpoint catalog once the server is running.

---

## Roadmap (planned, not shipped)

Per `Server2/doc/roadmap.md`, steps 1–13 (voice, memory, tools, sub-agents, proactive notifier, meeting mode) are complete. Not yet built:

- **Local STT fallback**: offline speech-to-text when Groq is unreachable.
- **Wake-word echo trap**: server-side detection of TTS audio leaking back into the mic.
- **File/image upload & attachments**: OCR, image captioning, chunked document analysis.
- **MCP adapter**: mirroring arbitrary MCP servers into the tool registry.
- **Mobile reference client and ESP32 firmware.**
- **Production hardening**: WebSocket backpressure, reconnection/session rehydration, CORS lockdown, graceful shutdown.
- **Observability**: OpenTelemetry tracing and a metrics dashboard.

Also not wired up yet: Gmail/Outlook OAuth (routes exist as 501 stubs) and the `send_email` / `draft_document` tools, which currently just report that no integration is connected.

---

## License

All rights reserved. This code is proprietary (see [`LICENSE`](LICENSE)). It is public for portfolio/reference purposes only; no license is granted to copy, modify, or redistribute it.
