# Vayumi Server 1 — Full Roadmap

**Source of truth:** [`PLAN.md`](../PLAN.md) v1.9  
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

## Phase 1 — Auth foundation ✅

Goal: users can register, log in, refresh tokens, manage sessions, and register push tokens. Server 2 can verify JWTs offline.

---

### Step 1 — Project scaffold + core infra ✅

**File:** [`doc/step-01.md`](step-01.md)  
**Estimated effort:** 1–2 days

**What the user can do after this step:**
- Start the Express server with health check at `GET /api/v1/health`.
- Connect to Postgres (Drizzle) and Redis on boot.
- Hit protected routes with middleware stack in correct order.

**Features delivered:**
- Express + TypeScript project scaffold
- Drizzle ORM + migrations
- Redis client, keys, helpers
- Core errors, middleware (auth, validate, rate limit, error handler)
- Pino logging

**What is NOT in this step:** Auth routes, user modules, integrations.

---

### Step 2 — Auth module ✅

**File:** [`doc/step-02.md`](step-02.md)  
**Estimated effort:** 2–3 days

**What the user can do after this step:**
- Register with email+password (disposable emails rejected).
- Log in, refresh tokens, log out (single session or all sessions).
- Google Sign-In at register/login.
- Verify email, reset/change password.
- Receive RS256 access JWT with `sub`, `sid`, `jti`, `scopes`.

**Features delivered:**
- Full `/api/v1/auth/*` route set
- Refresh token rotation + reuse detection (revoke session family)
- Redis blocklist for revoked access token `jti`
- SMTP email verification + password reset

---

### Step 3 — Sessions + push tokens + cron ✅

**File:** [`doc/step-03.md`](step-03.md)  
**Estimated effort:** 1 day

**What the user can do after this step:**
- List and revoke sessions via `/api/v1/sessions`.
- Register/delete push tokens via `/api/v1/notifications`.
- Expired tokens cleaned automatically by cron.

**Features delivered:**
- Sessions module
- Notifications module (push token CRUD only)
- `cleanExpiredTokens` cron job

---

## Phase 2 — User profile & settings ✅

Goal: users manage profile, avatar, and app settings.

---

### Step 4 — Users + settings + avatar storage ✅

**File:** [`doc/step-04.md`](step-04.md)  
**Estimated effort:** 1–2 days

**What the user can do after this step:**
- GET/PATCH profile, upload avatar, delete account.
- GET/PATCH notification, privacy, and appearance settings.

**Features delivered:**
- Users module with Supabase Storage for avatars
- Settings module + `user_settings` schema
- Registration creates default settings row

---

## Phase 3 — External integrations ← current

Goal: connect Gmail/Outlook, sync emails through AI pipeline, expose smart search API. Server 2 classifies and notifies; Server 1 owns OAuth and storage.

---

### Step 5 — Email pipeline foundation ✅

**File:** [`doc/step-05.md`](step-05.md)

**What the user can do after this step:**
- List connected integrations via `GET /api/v1/integrations` (empty until OAuth wired).
- Run `processIncomingEmail()` in isolation (classify → dedup → notify contract).
- Gmail/Outlook `GET …/connect` return 501 stubs (not OAuth yet).

**Features delivered:**
- `oauth_integrations` + `synced_emails` schemas + migration `0003`
- Shared pipeline: normalizer, masker, `processIncomingEmail()`, Server 2 client
- Redis sync lock (`setIfNotExists`), OAuth state key pattern
- `signInternalServiceJwt()` for Server 2 internal calls
- Integrations list router mounted

**What is NOT in this step:** Real OAuth, providers, emails API, cron jobs.

---

### Step 6 — Reminders & scheduled tasks ✅

**File:** [`doc/step-06.md`](step-06.md)  
**Estimated effort:** 2–3 days

**What the user can do after this step:**
- Create, list, update, delete, snooze, and cancel reminders via `/api/v1/reminders`.
- Server 2 agent creates reminders via service JWT (`source=agent`).
- Sync upcoming reminders for offline client scheduling via `GET /reminders/upcoming?days=2`.
- Due reminders fire via pg_cron → `POST /internal/reminders/fire` (or node-cron fallback).
- FCM push sent to user devices; Server 2 notified via `POST /internal/agent/event`.

**Features delivered:**
- `reminders` schema + migration `0004`
- Full reminders module with recurrence (`rrule`)
- Thin `fcm.provider.ts` + `sendPushToUser()`
- Generic Server 2 agent event client
- `fireReminders` node-cron fallback job

**What is NOT in this step:** Gmail/Outlook OAuth, emails API, APNS.

---

### Step 7 — Gmail OAuth + provider + disconnect ⬜

**File:** [`doc/step-07.md`](step-07.md)  
**Estimated effort:** 2–3 days

**What the user can do after this step:**
- Connect Gmail via OAuth (`GET /integrations/gmail/connect` → callback → tokens stored encrypted).
- Disconnect Gmail (revoke tokens, delete integration + synced emails for provider).
- Initial sync fetches emails through `processIncomingEmail()`.

**Features delivered:**
- `googleapis` dependency
- `gmail.types.ts`, `gmail.service.ts`, `gmail.controller.ts`, `gmail.provider.ts`
- Full Gmail router (connect, callback, disconnect)
- `IEmailProvider` implementation with historyId delta

**What is NOT in this step:** Outlook, emails search API, cron poller, webhooks.

---

### Step 8 — Outlook OAuth + provider + disconnect ⬜

**Estimated effort:** 2–3 days

**Features delivered:**
- `@microsoft/microsoft-graph-client` + `@azure/msal-node`
- Outlook service, controller, provider (deltaToken)
- Full Outlook router (connect, callback, disconnect)
- Initial sync on first connect

---

### Step 9 — Emails module ⬜

**Estimated effort:** 2 days

**What the user can do after this step:**
- Smart search via `GET /api/v1/emails` with combinable query params.
- Get email metadata, fetch live body from provider, trigger manual sync.
- Mark read/star (DB + provider with failure reconciliation).

**Features delivered:**
- `modules/emails/*` full CRUD/search API
- Router mounted at `/api/v1/emails`

---

### Step 10 — Cron jobs ⬜

**Estimated effort:** 1–2 days

**Features delivered:**
- `syncEmails` — staggered polling, batches of 5, respects sync lock
- `refreshOAuthTokens` — refresh before expiry
- `retryFailedAiProcessing` — re-fetch, re-mask, retry (max 3)
- `cleanOldEmails` — 90-day window, starred exempt
- `cron.bootstrap.ts` registers all Phase 3 email jobs

---

### Step 11 — Webhook stubs ⬜

**Estimated effort:** 1 day

**Features delivered:**
- `gmail.webhook.ts` — Pub/Sub push stub (HMAC verified, wired later)
- `outlook.webhook.ts` — Graph change notification stub
- Routes mounted but can return structured stub responses until production wiring

---

## Phase 4 — Push notification dispatch

Goal: when Server 2 returns `handled: false`, Server 1 sends push via APNS/FCM.

---

### Step 12 — APNS + FCM dispatch ⬜

**Estimated effort:** 2 days

**Features delivered:**
- `apns.provider.ts`, expand `fcm.provider.ts`
- `notifications.service.ts` full dispatch path
- Called from email pipeline when notify returns `handled: false`

---

## Phase 5 — Server 2 handshake

Goal: confirm cross-server auth contract is production-ready.

---

### Step 13 — Cross-server JWT + blocklist verification ⬜

**Estimated effort:** 0.5 day

**Features delivered:**
- Documented + verified RS256 public key sharing
- Redis blocklist works for both servers
- Service JWT (`scope: 'internal'`) rejected on user routes, accepted on Server 2 internal routes

---

## Cross-step rules

These apply to every step. If a step violates any of them, it is not done.

1. Existing API routes must still work after every step.
2. `npm run typecheck` and `npm run build` must pass.
3. No architecture changes without updating PLAN.md.
4. No new dependencies without adding to `package.json` and documenting in PLAN.md.
5. Server 1 never writes Server 2-owned tables.
6. OAuth state in Redis is one-time use — delete immediately on callback.
7. PII masking map stays in-memory only — never Redis or Postgres.
