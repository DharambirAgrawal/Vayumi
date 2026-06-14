# Step 05 — Email pipeline foundation

**Status:** ✅ done  
**Depends on:** step-04  
**Estimated effort:** 2–3 days  
**Owner:** you  
**Plan version:** documented in PLAN.md v1.8 (2026-05-13)

---

## Goal

Lay shared email infrastructure before wiring provider OAuth:

1. Drizzle schemas + migration for `oauth_integrations` and `synced_emails`.
2. Single pipeline function `processIncomingEmail()` — normalize → mask → classify → dedup → notify.
3. Server 2 HTTP client for `/internal/emails/classify` and `/internal/emails/notify` with retries.
4. Redis sync lock (`NX+EX`) and OAuth state key pattern.
5. `signInternalServiceJwt()` for service-to-service auth (no extra env secret).
6. Integrations list API + Gmail/Outlook router mounts with **501 stub** on `GET …/connect` only.

**There is no real OAuth, no emails search API, no cron poller, and no webhooks in this step.**

---

## Files this step created or changed

```
Server1/src/
├── core/config/
│   ├── index.ts                             CHANGED — Phase 3 env vars
│   └── integrations.ts                      NEW — typed email/Server2 config
├── core/db/schema/
│   ├── oauth-integrations.ts                NEW
│   ├── synced-emails.ts                     NEW
│   └── index.ts                             CHANGED — re-exports
├── core/db/migrations/
│   └── 0003_phase3_oauth_and_synced_emails.sql NEW
├── core/redis/
│   ├── index.ts                             CHANGED — setIfNotExists (NX+EX)
│   └── keys.ts                              CHANGED — emailSyncLock, integrationOAuthState, TTLs
├── core/utils/
│   ├── fetchRetry.ts                        NEW — fetch + AbortController timeout + backoff
│   ├── postgres.ts                          NEW — isUniqueViolation (PG code 23505)
│   ├── jwt.ts                               CHANGED — signInternalServiceJwt()
│   └── storage.ts                           CHANGED — optional contentType fix
├── routes/index.ts                          CHANGED — mount /integrations
├── modules/integrations/
│   ├── integrations.router.ts               NEW
│   ├── integrations.controller.ts           NEW
│   ├── integrations.service.ts              NEW — listForUser (no secrets)
│   ├── integrations.types.ts                NEW
│   ├── gmail/gmail.router.ts                NEW — GET /connect → 501 stub
│   ├── outlook/outlook.router.ts            NEW — GET /connect → 501 stub
│   └── shared/
│       ├── index.ts                         NEW — barrel exports
│       ├── email.types.ts                   NEW
│       ├── email.constants.ts               NEW — retry backoff constants
│       ├── provider.interface.ts            NEW — IEmailProvider
│       ├── email.normalizer.ts              NEW
│       ├── email.masker.ts                  NEW — MaskingSession (in-memory only)
│       ├── email.pipeline.ts                NEW — processIncomingEmail()
│       ├── server2.emailClient.ts           NEW — classify + notify
│       ├── emailSyncLock.ts                 NEW
│       └── tokenVault.ts                    NEW — AES-256 encrypt for OAuth tokens
└── .env.example                             CHANGED — SERVER2_INTERNAL_URL, EMAIL_*, ENCRYPTION_KEY
```

---

## Implementation summary

### Email pipeline (`processIncomingEmail`)

```
raw EmailMessage
  → mask PII ([PERSON_1], [EMAIL_1], …) — maskingMap in memory only
  → POST Server2 /internal/emails/classify (3 attempts, 2s/4s backoff)
  → on failure: save with ai_processed=false, category=informational
  → marketing/spam → DISCARD (nothing saved, no PII logged)
  → unmask keywords from maskingMap
  → INSERT synced_emails (catch 23505 unique violation → skip silently)
  → POST Server2 /internal/emails/notify (3 attempts, 1s/2s backoff)
  → handled=true → agent_delivered=true
  → handled=false → notification_fallback=true (Step 11 sends push)
```

Batch processing (for future cron): parallel groups of 5 via `Promise.allSettled`.

### Server 2 contract

- Service JWT: `{ scope: 'internal', iss: 'server1' }` signed with `JWT_PRIVATE_KEY`.
- Classify timeout: `EMAIL_AI_CLASSIFY_TIMEOUT_MS` (default 3000ms).
- Notify timeout: `EMAIL_NOTIFY_TIMEOUT_MS` (default 2000ms).
- Body sent to classify capped at `EMAIL_CLASSIFY_MAX_BODY_CHARS` (default 2000).

### API (partial)

| Method | Route | Status |
|---|---|---|
| GET | `/api/v1/integrations` | ✅ List connected integrations |
| GET | `/api/v1/integrations/gmail/connect` | ⚠️ 501 stub |
| GET | `/api/v1/integrations/outlook/connect` | ⚠️ 501 stub |

### Redis keys added

- `sync:lock:{userId}:{provider}` — TTL 5 min, NX+EX via `setIfNotExists`.
- `integration:state:{state}` — OAuth state → userId, TTL 10 min (used in Step 6).

---

## Acceptance test (passed)

1. **`npm run typecheck`** and **`npm run build`** — pass.
2. Migration `0003` applies cleanly (GIN index on `synced_emails.keywords`).
3. `GET /api/v1/integrations` returns `[]` for user with no connections.
4. `GET /api/v1/integrations/gmail/connect` returns `501` (not 404).
5. `processIncomingEmail()` unit path: marketing category → no DB row inserted.
6. Dedup: duplicate `(user_id, provider, provider_message_id)` → 23505 caught, no throw.
7. `signInternalServiceJwt()` produces token verifiable with `JWT_PUBLIC_KEY`.

---

## Out of scope

- Gmail/Outlook OAuth and providers (Steps 6–7).
- `GET /api/v1/emails` search API (Step 8).
- Cron jobs: sync, refresh, retry, cleanup (Step 9).
- Webhook stubs (Step 10).
- `googleapis`, Graph, MSAL packages (added in Steps 6–7).

---

## Notes for the next step

Step 6 replaces the Gmail 501 stub with full OAuth (state→Redis, token encrypt, initial sync through `processIncomingEmail()`), implements `IEmailProvider` for Gmail with `historyId` delta.
