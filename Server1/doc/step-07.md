# Step 07 — Gmail OAuth + provider + disconnect

**Status:** ⬜ pending  
**Depends on:** step-06 (reminders module — complete)  
**Estimated effort:** 2–3 days  
**Owner:** you

---

## Goal

Wire the full Gmail integration so an authenticated user can:

1. Start OAuth via `GET /api/v1/integrations/gmail/connect` (redirect to Google consent with state in Redis).
2. Complete OAuth via `GET /api/v1/integrations/gmail/callback` (state→userId, one-time Redis delete, token exchange, AES encrypt, upsert `oauth_integrations`).
3. Run **initial sync** on first connect — fetch emails back to `EMAIL_SYNC_WINDOW_DAYS`, each through `processIncomingEmail()`.
4. Disconnect via `DELETE /api/v1/integrations/gmail` — revoke tokens at Google, delete integration row, delete user's Gmail rows in `synced_emails`.
5. Implement `IEmailProvider` for Gmail with `historyId`-based delta fetch (used by Step 9 cron and Step 8 body/read/star).

**There is no Outlook work, no emails search API, no cron registration, and no Pub/Sub webhook in this step.**

---

## Files this step creates or changes

```
Server1/
├── package.json                              CHANGED — add googleapis
├── .env.example                              CHANGED — confirm GOOGLE_CLIENT_SECRET, GOOGLE_REDIRECT_URI documented
├── src/core/config/
│   └── integrations.ts                       CHANGED — Gmail OAuth client id/secret/redirect from env
├── src/modules/integrations/
│   ├── gmail/
│   │   ├── gmail.types.ts                    NEW
│   │   ├── gmail.service.ts                  NEW — OAuth URL, callback, disconnect, token refresh helper
│   │   ├── gmail.controller.ts               NEW
│   │   ├── gmail.provider.ts                 NEW — IEmailProvider (historyId delta, body, read, star)
│   │   └── gmail.router.ts                   CHANGED — connect, callback, disconnect routes
│   └── integrations.service.ts               CHANGED — optional helper to resolve provider instance
└── tests/                                    NEW or CHANGED — see acceptance test
    └── integration/gmail.provider.test.ts    NEW (or unit tests as appropriate)
```

---

## Detailed tasks

### 1. Dependencies

Add to `package.json`:

```
googleapis
```

Do **not** add Outlook packages yet (Step 7).

### 2. Config

Extend `core/config/integrations.ts` (or `core/config/index.ts` env schema) with:

- `GOOGLE_CLIENT_SECRET` (required when Gmail routes are used)
- `GOOGLE_REDIRECT_URI` — must match Google Cloud console callback URL pointing at `/api/v1/integrations/gmail/callback`

Reuse existing `GOOGLE_CLIENT_ID` from Phase 1 Google Sign-In (same Google Cloud project, different OAuth scopes).

Gmail OAuth scopes (minimum): `https://www.googleapis.com/auth/gmail.readonly` (adjust only if PLAN.md requires modify for read/star — use `gmail.modify` if needed for mark read/star on provider).

### 3. `gmail.service.ts`

Implement:

- **`buildConnectRedirect(userId)`**
  - Generate cryptographically random `state` (e.g. 32 bytes hex).
  - `RedisKeys.integrationOAuthState(state)` → `{ userId }`, TTL `RedisTTL.oauthState` (10 min).
  - Return Google OAuth consent URL with `state`, `access_type=offline`, `prompt=consent` (to obtain refresh token on first connect).

- **`handleCallback(code, state)`**
  - Lookup Redis; if missing/expired → throw `400 INVALID_STATE`.
  - **Delete state key immediately** (one-time use — Design Rule 30).
  - Exchange `code` for tokens via googleapis.
  - Encrypt `access_token` + `refresh_token` via `tokenVault.encrypt()`.
  - Upsert `oauth_integrations` for `userId` + `provider='gmail'`.
  - Call **`runInitialSync(userId, integrationId)`** (see below).
  - Return redirect URL or JSON success payload (match existing app pattern — check `APP_URL` / mobile deep link convention in PLAN.md).

- **`disconnect(userId)`**
  - Load integration; revoke token at Google if present.
  - Delete `oauth_integrations` row.
  - Delete all `synced_emails` where `user_id` + `provider='gmail'`.

- **`runInitialSync(userId, integrationId)`**
  - Acquire sync lock via `emailSyncLock` (skip or no-op if lock held — log and return).
  - Use `gmail.provider` to list messages within `EMAIL_SYNC_WINDOW_DAYS`.
  - Process each through `processIncomingEmail()` in parallel batches of 5 (`Promise.allSettled`).
  - Persist `historyId` (or equivalent) in `oauth_integrations.sync_state`.

### 4. `gmail.provider.ts`

Implement `IEmailProvider`:

| Method | Behavior |
|---|---|
| `providerId` | `'gmail'` |
| `fetchDelta(syncState)` | Use stored `historyId`; call Gmail history API; return normalized `EmailMessage[]` + updated `nextSyncState` |
| `fetchBodyText(id)` | Live fetch from Gmail API — plain text, never stored in DB |
| `setReadState(id, isRead)` | Gmail API modify labels |
| `setStarredState(id, isStarred)` | Gmail API modify labels |

Use `email.normalizer.ts` to produce unified `EmailMessage` shape.

Token refresh: if access token expired, refresh using stored encrypted refresh token, re-encrypt, update DB row.

### 5. `gmail.controller.ts` + `gmail.router.ts`

| Route | Auth | Handler |
|---|---|---|
| `GET /connect` | Yes (`authenticate`) | Redirect to Google |
| `GET /callback` | No (state verified) | `handleCallback`, redirect/JSON |
| `DELETE /` | Yes | `disconnect` |

Remove the 501 stub on `/connect`.

Mount paths under existing integrations router prefix (`/api/v1/integrations/gmail/...`).

### 6. Error handling

- Invalid/expired OAuth state → `400` with code `INVALID_STATE`.
- Google API errors → log with Pino; surface safe message to client.
- Unique violation on email insert → already handled in pipeline (`23505` catch).

---

## Acceptance test

Run all of these before marking the step done:

1. **`npm run typecheck`** — zero errors.
2. **`npm run build`** — compiles cleanly.
3. **Unit/integration:** `gmail.provider` normalizes a fixture Gmail API payload into `EmailMessage`.
4. **Unit:** OAuth state stored in Redis and deleted after successful callback (mock Redis).
5. **Manual or integration (if credentials available):**
   - Authenticated `GET /integrations/gmail/connect` returns 302 to Google (not 501).
   - After callback, `GET /integrations` lists Gmail with `providerAccountId`.
   - `synced_emails` rows appear for non-marketing messages after initial sync.
   - `DELETE /integrations/gmail` removes integration and Gmail synced rows.

If Google credentials are not available in dev, document which tests ran with mocks and which were skipped — but provider normalization and state one-time-use must still have automated tests.

---

## Out of scope

- Outlook OAuth (Step 7).
- `GET /api/v1/emails` search API (Step 8).
- Cron poller `syncEmails.ts` (Step 9) — but provider must implement `fetchDelta` ready for cron.
- `gmail.webhook.ts` Pub/Sub stub (Step 10).
- Push notification fallback (Step 11).

---

## Risks and how we'll catch them

| Risk | Mitigation |
|---|---|
| No refresh token on reconnect | Use `prompt=consent` + `access_type=offline` on connect |
| Initial sync overload | Batch of 5 via `Promise.allSettled`; respect sync lock |
| Token stored plaintext | Always `tokenVault.encrypt()` before DB write |
| State replay attack | Delete Redis state before code exchange |

---

## Notes for the next step

Step 7 mirrors this pattern for Outlook: MSAL + Graph client, `deltaToken` in `sync_state`, same OAuth state→Redis flow, same initial sync through `processIncomingEmail()`.
