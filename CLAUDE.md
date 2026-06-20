# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository layout

This repo holds two **independent** backend services. They are different languages and run separately:

- **`Server1/`** — REST API (Node.js + TypeScript + Express). Auth, users, sessions, settings, meetings sync, reminders, push tokens. This is the live, deployed backend the mobile app talks to.
- **`Server2/`** — Voice-first multi-agent AI backend (Python 3.11 + FastAPI + WebSocket). Local LLM (llama-server), STT/TTS, agent orchestration, vector memory (LanceDB). Spec-driven — see `Server2/PLAN.md`, `Server2/doc/tracker.md`, `Server2/doc/roadmap.md`.

The Expo/React Native mobile app is a **separate repo** (`../vayumi-app`), not in this tree. Server1 is its REST backend; Server2 is the voice/agent backend. Server1 can emit internal "agent events" to Server2 (`SERVER2_INTERNAL_URL`), but that link is optional and Server2 is not currently hosted.

When working on a task, stay within the relevant service — they share no code.

---

## Server1 (Node/TypeScript) — `cd Server1`

### Commands
- `npm run dev` — watch-mode dev server (`tsx watch src/server.ts`), loads `.env`
- `npm run build` — `tsc` → `dist/`
- `npm run typecheck` — `tsc --noEmit`. **There is no test runner or linter** — verify changes with `typecheck` + `build` + running the server.
- `npm start` — `node dist/server.js` (runs the compiled output; does not rebuild)
- `npm run db:generate` — author a Drizzle migration from schema changes (see DB note below)

### Architecture
- **Entry/wiring:** `src/server.ts` (boot: verify DB → run migrations → cron → listen) → `src/app.ts` (Express middleware chain) → `src/routes/index.ts` (mounts every module router under `/api/v1`, internal routers under `/internal`).
- **Module pattern:** each domain under `src/modules/<name>/` is a vertical slice — `*.router.ts` (routes + middleware), `*.controller.ts` (thin, unwraps req → calls service), `*.service.ts` (business logic + DB), `*.validators.ts` (zod request schemas), `*.types.ts`. To add an endpoint: extend these files, then mount the router in `routes/index.ts`.
- **Config:** `src/core/config/index.ts` validates `process.env` with zod and is the single source of truth; sub-configs (`app.ts`, `jwt.ts`, `integrations.ts`, `reminders.ts`) derive from it. Empty env vars are treated as unset via the `optionalString` helper. Config loads via `import "dotenv/config"`, so locally it reads `.env`; in production (Heroku) there is no `.env` and it uses injected config vars.
- **Database:** Drizzle ORM over `postgres.js` (`src/core/db/index.ts`), schema in `src/core/db/schema/*`. **Migrations are raw `.sql` files** in `src/core/db/migrations/` applied **on boot** by a custom runner (advisory-lock guarded, tracked in `__app_migrations`) — *not* `drizzle-kit migrate`. So adding a migration = drop a numbered `NNNN_name.sql` file; it applies automatically next boot (unless `DATABASE_AUTO_MIGRATE=false`). Connects to Supabase via the **transaction pooler** with SSL.
- **Auth:** RS256 JWT access tokens + opaque refresh tokens. Refresh tokens are validated against the Postgres `sessions` table (hashed), and `authenticate` middleware re-checks the session is active on every request. `authenticateUserOrService` additionally accepts an internal service JWT (`scope: "internal"`, `iss: "server1"`) for server-to-server calls.
- **No Redis.** It was deliberately removed; everything is Postgres now — rate limiting is a `rate_limits` table (atomic fixed-window upsert, fails open), the reminder fire-lock is a `pg_advisory_lock` on a reserved connection. Do not reintroduce Redis without a real multi-instance reason.
- **Reminders:** an in-process `node-cron` job (`src/modules/cron/`) fires due reminders every minute via `remindersService.fireRemindersNow()`. There is also an internal HTTP trigger (`POST /internal/reminders/fire`) guarded by `INTERNAL_REMINDER_SECRET` for an external scheduler — currently unused.
- **Email:** OCI Email Delivery (HTTPS data-plane API, not SMTP). Both email verification and password reset use **6-digit numeric codes** delivered by email — there are no web reset links (the app is native-only).
- **File storage:** one Supabase Storage bucket (`SUPABASE_STORAGE_BUCKET`); file categories are key prefixes within it, centralized in `StorageKeys` in `src/core/utils/storage.ts` (e.g. `avatars/<userId>/...`). Add a new category there, not a new bucket.
- **Dormant code:** the Gmail/Outlook integrations (`src/modules/integrations/gmail|outlook`) are 501 stubs and the email-classification pipeline in `integrations/shared/` is unreachable (depends on the unhosted Server2). Don't assume it runs.

### Deploy
GitHub Actions (`.github/workflows/server1-cicd.yml`) deploys Server1 to Heroku on **push to `main`** (builds + tests on PRs to main, but only `main` pushes deploy). It deploys the `Server1/` subdirectory as the app root via `git subtree split`. `Procfile` runs `node dist/server.js`. The Heroku buildpack runs `build` then prunes devDependencies — so the runtime must never invoke `tsc` (no `prestart` rebuild). Never set a `PORT` config var on Heroku; the app must bind to Heroku's injected `$PORT`. Dev and prod are separate Supabase projects; `.env` = dev, `.env.prod` = prod (its values are copied into Heroku config vars).

---

## Server2 (Python/FastAPI) — `cd Server2`

### Commands
- `python3.11 -m venv venv && source venv/bin/activate && pip install -r requirements.txt` — first-time setup (also `python -m spacy download en_core_web_sm` and `scrapling install`)
- `uvicorn server.app:app --port 8080` — run the server (prefix `LOG_LEVEL=debug` for verbose logs)
- `pytest` — run tests; single test: `pytest tests/<file>.py::<test_name>`

### Architecture
FastAPI app at `server/app.py`; logic lives under `server/` in `orchestrator/`, `subagents/`, `tools/`, `engine/`, `voice/` (stt/tts/vad), `memory/`, `transport/` (WebSocket), `db/`. It is a **frozen-spec project** — read `PLAN.md` (architecture; §7.10.1 = current main turn flow), `doc/tracker.md` (progress/flows), and `doc/roadmap.md` before changing a subsystem. Requires Postgres (`DATABASE_URL`), Redis (`REDIS_URL`), a local `llama-server` binary + GGUF model under `models/`, and a Groq API key (`GROQ_API_KEY`) for STT. Unlike Server1, Server2 **does** use Redis.
