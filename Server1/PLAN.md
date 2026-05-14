# Server 1 — Architecture Plan
**Version:** 1.7
**Status:** Phase 3 in progress
**Last updated:** 2026-05-10

---

## Changelog

| Version | Change |
|---|---|
| 1.7 | Audit fixes: removed `SERVER2_SERVICE_TOKEN` env var (service JWT signed with existing `JWT_PRIVATE_KEY`). Removed contradictory `pipelineMaskingMap` Redis key (memory-only, never persisted). Fixed `cron.bootstrap.ts` and `routes/index.ts` status to ⚠️. Documented OAuth callback user-ID resolution via state→Redis. Added `updatedAt` to `synced_emails`. Added subject index + keywords GIN index to `synced_emails`. Replaced `@azure/identity` with `@azure/msal-node`. Removed `axios` (native fetch). Fixed design rule 21 (initial sync on first connect). Added retry cron re-fetch note. Added starred-email exemption to `cleanOldEmails`. Fixed sync lock TTL description. Documented `POST /sync` 202 when lock active. Documented `23505` catch for dedup. Documented provider failure handling on `PATCH /read` and `PATCH /star`. Added `EMAIL_POLL_INTERVAL_MINUTES` cron expression note. |
| 1.6 | Full Phase 3 design. Added `synced_emails` + `oauth_integrations` schemas. Added email pipeline, masking layer, AI classify call, retry logic, Server 2 notify contract. Added smart search, on-demand body fetch, mark read/star. Added `emails` module. Added 4 new cron jobs. Added webhook stubs. |
| 1.5 | Phase 2 complete. Avatar storage switched to Supabase Storage. |
| 1.4 | Phase 1 marked complete. Health route. `PASSWORD_RESET_URL` moved. Phase 2 checklist expanded. |
| 1.3 | Phase 1 implemented. Auto-migration, Google token verification, unverified-email blocking. |
| 1.2 | `RedisTTL`. `cache.remember()`. DB indexes. `node-cron`, `mailchecker`. `validate` factory. `NotFoundError`. |
| 1.1 | Google Sign-In. `user_identities`. Email verification. Push token cascade fix. |
| 1.0 | Initial plan |

---

## Stack

- **Runtime:** Node.js + TypeScript
- **Framework:** Express.js
- **ORM:** Drizzle ORM
- **Database:** Supabase PostgreSQL
- **Cache / Session store:** Redis (node-redis; cloud.redislabs.com)
- **JWT algorithm:** RS256 (asymmetric — private key signs, public key verifies)
- **Validation:** Zod
- **Logger:** Pino

Supabase is used as the managed Postgres provider. All code stays generic (`DATABASE_URL`, Drizzle migrations, plain SQL) — no Supabase auth features used.

---

## Auth Rules

- Email + password registration accepted for all real providers (Gmail, Outlook, edu, corporate, etc.)
- Temporary / disposable emails rejected at registration (via `mailchecker`)
- Google Sign-In supported at registration and login — same endpoint, find or create account
- Email/password login requires verified email; unverified users receive `403 EMAIL_NOT_VERIFIED`
- More providers (Apple, GitHub, etc.) slot into `user_identities` with zero schema changes
- Two-token system: short-lived access token (15 min) + long-lived refresh token (90 days)
- Refresh token rotated on every use; reusing an old one revokes the entire session family
- Refresh tokens stored hashed in DB and indexed in Redis
- Revoked access tokens tracked in Redis blocklist by `jti` (auto-expires at token TTL)
- Mobile clients store refresh token in OS secure keychain — never in app storage
- Email verification required after email+password registration; Google Sign-In users are auto-verified

---

## Session & Device Tracking

Each login (any method) creates one session record:

| Field | Type | Notes |
|---|---|---|
| `id` | UUID | Primary key |
| `user_id` | UUID FK | Indexed |
| `device_type` | enum | `mobile_ios` · `mobile_android` · `web` · `hardware` |
| `device_name` | string | e.g. "iPhone 15 Pro" |
| `device_fingerprint` | string | Hashed UA + platform |
| `refresh_token_hash` | string | bcrypt hashed |
| `is_active` | boolean | |
| `last_seen_at` | timestamp | |
| `updated_at` | timestamp | |
| `created_at` | timestamp | |
| `expires_at` | timestamp | |
| `revoked_at` | timestamp | nullable |

JWT access token payload: `sub` (user ID), `sid` (session ID), `jti`, `device_type`, `scopes`, `iat`, `exp`.

Server 2 verifies tokens offline using the shared public key. Both servers check Redis blocklist for revoked `jti` values.

---

## Server 2 Contract (Phase 3)

Server 1 never cares what Server 2 does internally. Server 1 makes two types of calls to Server 2.

**Service token** — Server 1 signs a JWT using the existing `JWT_PRIVATE_KEY` with payload `{ scope: 'internal', iss: 'server1' }` and no expiry. Server 2 verifies it with `JWT_PUBLIC_KEY`. A normal user JWT (any other scope) hitting a Server 2 internal route is rejected immediately. No extra env var or pre-shared secret needed.

**AI classify call** — before saving any email:
```
POST {SERVER2_INTERNAL_URL}/internal/emails/classify
Authorization: Bearer {signed service JWT}
Body: { messageId, subject, snippet, fromEmail(masked), fromName(masked), body(masked, max 2000 chars) }
Response: { category, keywords[], summary, priorityScore }
  category: 'marketing' | 'spam' | 'transactional' | 'informational' | 'action_required' | 'urgent'
```
- Hard timeout: `EMAIL_AI_CLASSIFY_TIMEOUT_MS` (default 3000ms)
- Max 3 attempts, backoff: 2s then 4s
- On all failures: save with `ai_processed=false`, `category='informational'`, no keywords

**Notify call** — after saving email to DB:
```
POST {SERVER2_INTERNAL_URL}/internal/emails/notify
Authorization: Bearer {signed service JWT}
Body: { userId, emailId, category, priorityScore, summary, fromName, fromEmail, subject }
Response: { handled: true } | { handled: false }
```
- Hard timeout: `EMAIL_NOTIFY_TIMEOUT_MS` (default 2000ms)
- Max 3 attempts, backoff: 1s then 2s
- `handled: true` → mark `agent_delivered=true` in DB, done
- `handled: false` → Phase 4 sends push notification; mark `notification_fallback=true` in DB
- On all failures → same as `handled: false`

Both calls use native `fetch` with `AbortController` for timeout. No extra HTTP library needed.

---

## Email Pipeline

Single function `processIncomingEmail()` in `integrations/shared/email.pipeline.ts`. Called by both cron poller and webhook handler. Never duplicated.

```
rawEmail (from Gmail API or Graph API)
  ↓
1. Normalize → unified EmailMessage shape
  ↓
2. Mask PII → { maskedEmail, maskingMap }
   Names + emails replaced with [PERSON_1], [EMAIL_1], etc.
   maskingMap held in memory for this run only — never written to Redis or DB
  ↓
3. POST to Server 2 /internal/emails/classify  (timeout + retry)
   ↓ failure after 3 attempts
   Save with ai_processed=false, category=informational → skip to step 6
   ↓ success
4. category = 'marketing' or 'spam' → DISCARD. Return immediately.
   Nothing saved. maskingMap discarded. No PII logged anywhere.
   ↓ important category
5. Unmask keywords using in-memory maskingMap → real names restored
   maskingMap discarded after this step
  ↓
6. Dedup check: INSERT with unique constraint on (user_id, provider, provider_message_id)
   → PostgreSQL error code 23505 (unique violation): catch specifically, skip silently, return
   → Success: row inserted into synced_emails
  ↓
7. POST to Server 2 /internal/emails/notify  (timeout + retry)
   → handled=true  → mark agent_delivered=true in DB
   → handled=false → Phase 4 sends push notification; mark notification_fallback=true
   → all retries fail → same as handled=false
```

**Batch processing (polling):** parallel groups of 5 emails via `Promise.allSettled`. One failure never blocks the rest.

**Webhook path (Pub/Sub / Graph — future):** single email → same `processIncomingEmail()`. No pipeline changes needed when switching to real-time.

**Initial sync (first connect):** `syncState` is empty on first connect. Provider service fetches emails going back `EMAIL_SYNC_WINDOW_DAYS` days, sets initial `historyId` (Gmail) or `deltaToken` (Outlook) after this first batch. All subsequent syncs are delta only.

**Sync lock:** Redis lock per `(userId, provider)` — TTL 5 minutes — prevents concurrent syncs for the same user. If `POST /api/v1/emails/sync` is called while lock is active, return `202 Accepted` with `{ message: 'sync already in progress' }`. Do not error.

---

## Folder Structure

```
server1/
│
├── src/
│   │
│   ├── core/
│   │   ├── db/
│   │   │   ├── index.ts                        # ✅
│   │   │   ├── schema/
│   │   │   │   ├── users.ts                    # ✅
│   │   │   │   ├── user-identities.ts          # ✅
│   │   │   │   ├── sessions.ts                 # ✅
│   │   │   │   ├── push-tokens.ts              # ✅
│   │   │   │   ├── email-verifications.ts      # ✅
│   │   │   │   ├── password-reset-tokens.ts    # ✅
│   │   │   │   ├── settings.ts                 # ✅
│   │   │   │   ├── oauth-integrations.ts       # ⬜ Phase 3
│   │   │   │   ├── synced-emails.ts            # ⬜ Phase 3
│   │   │   │   └── index.ts                    # ✅ re-exports all schemas
│   │   │   └── migrations/                     # ✅
│   │   │
│   │   ├── redis/
│   │   │   ├── index.ts                        # ✅
│   │   │   ├── keys.ts                         # ✅ — Phase 3 adds emailSyncLock + integrationOAuthState
│   │   │   └── helpers.ts                      # ✅
│   │   │
│   │   ├── config/
│   │   │   ├── index.ts                        # ✅
│   │   │   ├── jwt.ts                          # ✅
│   │   │   └── app.ts                          # ✅
│   │   │
│   │   ├── middleware/
│   │   │   ├── authenticate.ts                 # ✅
│   │   │   ├── requireScopes.ts                # ✅
│   │   │   ├── rateLimiter.ts                  # ✅
│   │   │   ├── validate.ts                     # ✅
│   │   │   ├── requestLogger.ts                # ✅
│   │   │   └── errorHandler.ts                 # ✅
│   │   │
│   │   ├── errors/
│   │   │   ├── AppError.ts                     # ✅
│   │   │   ├── AuthError.ts                    # ✅
│   │   │   ├── ValidationError.ts              # ✅
│   │   │   ├── NotFoundError.ts                # ✅
│   │   │   └── index.ts                        # ✅
│   │   │
│   │   ├── utils/
│   │   │   ├── crypto.ts                       # ✅
│   │   │   ├── jwt.ts                          # ✅
│   │   │   ├── pagination.ts                   # ✅
│   │   │   ├── date.ts                         # ✅
│   │   │   ├── logger.ts                       # ✅
│   │   │   └── storage.ts                      # ✅ Supabase Storage
│   │   │
│   │   └── types/
│   │       ├── express.d.ts                    # ✅
│   │       └── index.ts                        # ✅
│   │
│   ├── modules/
│   │   │
│   │   ├── auth/                               # ✅ Phase 1
│   │   │   ├── auth.router.ts                  # ✅
│   │   │   ├── auth.controller.ts              # ✅
│   │   │   ├── auth.service.ts                 # ✅
│   │   │   ├── auth.validators.ts              # ✅
│   │   │   ├── auth.types.ts                   # ✅
│   │   │   └── auth.helpers.ts                 # ✅
│   │   │
│   │   ├── sessions/                           # ✅ Phase 1
│   │   │   ├── sessions.router.ts              # ✅
│   │   │   ├── sessions.controller.ts          # ✅
│   │   │   ├── sessions.service.ts             # ✅
│   │   │   └── sessions.types.ts               # ✅
│   │   │
│   │   ├── users/                              # ✅ Phase 2
│   │   │   ├── users.router.ts                 # ✅
│   │   │   ├── users.controller.ts             # ✅
│   │   │   ├── users.service.ts                # ✅
│   │   │   ├── users.validators.ts             # ✅
│   │   │   └── users.types.ts                  # ✅
│   │   │
│   │   ├── settings/                           # ✅ Phase 2
│   │   │   ├── settings.router.ts              # ✅
│   │   │   ├── settings.controller.ts          # ✅
│   │   │   ├── settings.service.ts             # ✅
│   │   │   ├── settings.validators.ts          # ✅
│   │   │   └── settings.types.ts               # ✅
│   │   │
│   │   ├── integrations/                       # ⬜ Phase 3
│   │   │   ├── integrations.router.ts          # ⬜ mounts gmail + outlook sub-routers
│   │   │   ├── integrations.controller.ts      # ⬜ list connected integrations
│   │   │   ├── integrations.service.ts         # ⬜
│   │   │   ├── integrations.types.ts           # ⬜
│   │   │   │
│   │   │   ├── shared/
│   │   │   │   ├── email.types.ts              # ⬜ unified EmailMessage type
│   │   │   │   ├── provider.interface.ts       # ⬜ IEmailProvider interface
│   │   │   │   ├── email.normalizer.ts         # ⬜ raw → EmailMessage
│   │   │   │   ├── email.masker.ts             # ⬜ mask/unmask PII (in-memory only)
│   │   │   │   └── email.pipeline.ts           # ⬜ processIncomingEmail()
│   │   │   │
│   │   │   ├── gmail/
│   │   │   │   ├── gmail.router.ts             # ⬜
│   │   │   │   ├── gmail.controller.ts         # ⬜
│   │   │   │   ├── gmail.service.ts            # ⬜ OAuth, token storage, watch stub
│   │   │   │   ├── gmail.provider.ts           # ⬜ IEmailProvider, historyId delta
│   │   │   │   ├── gmail.webhook.ts            # ⬜ Pub/Sub stub — wired in future
│   │   │   │   └── gmail.types.ts              # ⬜
│   │   │   │
│   │   │   └── outlook/
│   │   │       ├── outlook.router.ts           # ⬜
│   │   │       ├── outlook.controller.ts       # ⬜
│   │   │       ├── outlook.service.ts          # ⬜ OAuth, token storage, subscription stub
│   │   │       ├── outlook.provider.ts         # ⬜ IEmailProvider, deltaToken
│   │   │       ├── outlook.webhook.ts          # ⬜ Graph change notification stub — wired in future
│   │   │       └── outlook.types.ts            # ⬜
│   │   │
│   │   ├── emails/                             # ⬜ Phase 3
│   │   │   ├── emails.router.ts                # ⬜
│   │   │   ├── emails.controller.ts            # ⬜
│   │   │   ├── emails.service.ts               # ⬜
│   │   │   ├── emails.validators.ts            # ⬜
│   │   │   └── emails.types.ts                 # ⬜
│   │   │
│   │   ├── notifications/                      # ✅ Phase 1 partial · ⬜ Phase 4 full
│   │   │   ├── notifications.router.ts         # ✅
│   │   │   ├── notifications.controller.ts     # ✅
│   │   │   ├── notifications.service.ts        # ✅
│   │   │   ├── notifications.validators.ts     # ✅
│   │   │   ├── notifications.types.ts          # ✅
│   │   │   ├── apns.provider.ts                # ⬜ Phase 4
│   │   │   └── fcm.provider.ts                 # ⬜ Phase 4
│   │   │
│   │   └── cron/
│   │       ├── cron.bootstrap.ts               # ⚠️ Phase 3 adds 4 new jobs
│   │       ├── jobs/
│   │       │   ├── cleanExpiredTokens.ts       # ✅ Phase 1
│   │       │   ├── syncEmails.ts               # ⬜ Phase 3
│   │       │   ├── refreshOAuthTokens.ts       # ⬜ Phase 3
│   │       │   ├── retryFailedAiProcessing.ts  # ⬜ Phase 3
│   │       │   └── cleanOldEmails.ts           # ⬜ Phase 3
│   │       └── cron.types.ts                   # ✅
│   │
│   ├── routes/
│   │   └── index.ts                            # ⚠️ Phase 3 mounts integrations + emails routers
│   │
│   └── app.ts                                  # ✅
│
├── server.ts                                   # ✅
├── .env.example                                # ✅
├── drizzle.config.ts                           # ✅
├── tsconfig.json                               # ✅
└── package.json                                # ✅
```

**Status key:** ✅ done · 🔄 in progress · ⚠️ partial (needs Phase 3 updates) · ⬜ not started

---

## API Routes

### Health

| Method | Route | Protected | Notes | Status |
|---|---|---|---|---|
| GET | `/api/v1/health` | No | Service health check | ✅ |

### Phase 1 — Auth · `/api/v1/auth`

| Method | Route | Protected | Status |
|---|---|---|---|
| POST | `/register` | No | ✅ |
| POST | `/login` | No | ✅ |
| POST | `/google` | No | ✅ |
| GET | `/verify-email` | No | ✅ |
| POST | `/verify-email/resend` | Yes | ✅ |
| POST | `/verify-email/resend/request` | No | ✅ |
| POST | `/token/refresh` | No | ✅ |
| POST | `/logout` | Yes | ✅ |
| POST | `/logout/all` | Yes | ✅ |
| POST | `/password/forgot` | No | ✅ |
| POST | `/password/reset` | No | ✅ |
| POST | `/password/change` | Yes | ✅ |
| GET | `/me` | Yes | ✅ |

### Phase 1 — Sessions · `/api/v1/sessions`

| Method | Route | Protected | Status |
|---|---|---|---|
| GET | `/` | Yes | ✅ |
| DELETE | `/:sessionId` | Yes | ✅ |

### Phase 1 — Notifications · `/api/v1/notifications`

| Method | Route | Protected | Status |
|---|---|---|---|
| POST | `/push-token` | Yes | ✅ |
| DELETE | `/push-token` | Yes | ✅ |

### Phase 2 — Users · `/api/v1/users`

| Method | Route | Protected | Status |
|---|---|---|---|
| GET | `/profile` | Yes | ✅ |
| PATCH | `/profile` | Yes | ✅ |
| POST | `/avatar` | Yes | ✅ |
| DELETE | `/account` | Yes | ✅ |

### Phase 2 — Settings · `/api/v1/settings`

| Method | Route | Protected | Status |
|---|---|---|---|
| GET | `/` | Yes | ✅ |
| PATCH | `/notifications` | Yes | ✅ |
| PATCH | `/privacy` | Yes | ✅ |
| PATCH | `/appearance` | Yes | ✅ |

### Phase 3 — Integrations · `/api/v1/integrations`

| Method | Route | Protected | Notes | Status |
|---|---|---|---|---|
| GET | `/` | Yes | List connected integrations with status | ⬜ |
| GET | `/gmail/connect` | Yes | Generates state (encodes userId), stores in Redis, redirects to Google OAuth | ⬜ |
| GET | `/gmail/callback` | No | Reads state from Redis to get userId, exchanges code for tokens, stores encrypted | ⬜ |
| DELETE | `/gmail` | Yes | Disconnect — revoke tokens, remove integration, delete synced emails for this provider | ⬜ |
| POST | `/gmail/webhook` | No | Pub/Sub push — HMAC verified — stub now, wired in future | ⬜ |
| GET | `/outlook/connect` | Yes | Generates state (encodes userId), stores in Redis, redirects to Microsoft OAuth | ⬜ |
| GET | `/outlook/callback` | No | Reads state from Redis to get userId, exchanges code for tokens, stores encrypted | ⬜ |
| DELETE | `/outlook` | Yes | Disconnect — revoke tokens, remove integration, delete synced emails for this provider | ⬜ |
| POST | `/outlook/webhook` | No | Graph change notification — token verified — stub now, wired in future | ⬜ |

### Phase 3 — Emails · `/api/v1/emails`

| Method | Route | Protected | Notes | Status |
|---|---|---|---|---|
| GET | `/` | Yes | Smart search — flexible query params | ⬜ |
| GET | `/:id` | Yes | Email metadata + snippet from DB | ⬜ |
| GET | `/:id/body` | Yes | Full body fetched live from provider — never stored | ⬜ |
| POST | `/sync` | Yes | Trigger delta sync. Returns `202` if sync lock active | ⬜ |
| PATCH | `/:id/read` | Yes | Mark read in DB + provider. If provider fails: keep DB update, log, reconcile on next delta | ⬜ |
| PATCH | `/:id/star` | Yes | Star/unstar in DB + provider. Same failure handling as `/read` | ⬜ |

**Smart search query params for `GET /api/v1/emails`:**
```
?provider=gmail|outlook|all    filter by provider
?from=email@domain.com         exact match on from_email
?fromName=Alice                case-insensitive LIKE on from_name
?subject=invoice               case-insensitive LIKE on subject (indexed)
?after=2026-05-01              received_at >= date
?before=2026-05-10             received_at <= date
?unread=true                   is_read = false
?starred=true                  is_starred = true
?hasAttachment=true            has_attachments = true
?category=action_required      exact match on category
?label=inbox                   label exists in labels jsonb array
?threadId=xxx                  all emails in a thread
?keywords=invoice,payment      any of these terms exist in AI keywords array (GIN indexed)
?limit=20                      default 20, max 100
?cursor=xxx                    cursor pagination
```
All params optional and combinable. Query built dynamically — only active params become WHERE clauses.

### Phase 4+ — Push dispatch
> Routes added when Phase 4 begins.

### Phase 5+ — Server 2 handshake
> Internal route mounting added when Phase 5 begins.

---

## Database Schema

### Relationship map

```
users (1) ──< user_identities (many)
users (1) ──< sessions (many)
users (1) ──< push_tokens (many)
users (1) ──< email_verifications (many)
users (1) ──< password_reset_tokens (many)
users (1) ── user_settings (1)
users (1) ──< oauth_integrations (many)   — Phase 3 — one row per connected provider
users (1) ──< synced_emails (many)        — Phase 3 — AI-enriched, 90-day rolling window
```

### Schema

```typescript
// users
export const users = pgTable("users", {
  id:         uuid("id").primaryKey().defaultRandom(),
  email:      varchar("email", { length: 255 }).notNull().unique(),
  name:       varchar("name", { length: 100 }),
  avatarUrl:  text("avatar_url"),
  isVerified: boolean("is_verified").default(false).notNull(),
  createdAt:  timestamp("created_at").defaultNow().notNull(),
  updatedAt:  timestamp("updated_at").defaultNow().notNull(),
  deletedAt:  timestamp("deleted_at"),
});

// user_identities
export const userIdentities = pgTable("user_identities", {
  id:                uuid("id").primaryKey().defaultRandom(),
  userId:            uuid("user_id").notNull().references(() => users.id, { onDelete: "cascade" }),
  provider:          varchar("provider", { length: 30 }).notNull(),
  providerAccountId: text("provider_account_id").notNull(),
  passwordHash:      text("password_hash"),
  createdAt:         timestamp("created_at").defaultNow().notNull(),
  updatedAt:         timestamp("updated_at").defaultNow().notNull(),
}, (t) => ({
  providerAccountUniq: uniqueIndex("ui_provider_account_idx").on(t.provider, t.providerAccountId),
  userIdIdx:           index("ui_user_id_idx").on(t.userId),
}));

// sessions
export const sessions = pgTable("sessions", {
  id:                uuid("id").primaryKey().defaultRandom(),
  userId:            uuid("user_id").notNull().references(() => users.id, { onDelete: "cascade" }),
  deviceType:        varchar("device_type", { length: 30 }).notNull(),
  deviceName:        varchar("device_name", { length: 100 }),
  deviceFingerprint: text("device_fingerprint"),
  refreshTokenHash:  text("refresh_token_hash").notNull(),
  isActive:          boolean("is_active").default(true).notNull(),
  lastSeenAt:        timestamp("last_seen_at").defaultNow().notNull(),
  createdAt:         timestamp("created_at").defaultNow().notNull(),
  updatedAt:         timestamp("updated_at").defaultNow().notNull(),
  expiresAt:         timestamp("expires_at").notNull(),
  revokedAt:         timestamp("revoked_at"),
}, (t) => ({
  userIdIdx:  index("sessions_user_id_idx").on(t.userId),
  expiryIdx:  index("sessions_expires_at_idx").on(t.expiresAt),
  activeIdx:  index("sessions_is_active_idx").on(t.isActive),
}));

// push_tokens
export const pushTokens = pgTable("push_tokens", {
  id:        uuid("id").primaryKey().defaultRandom(),
  userId:    uuid("user_id").notNull().references(() => users.id, { onDelete: "cascade" }),
  sessionId: uuid("session_id"),
  token:     text("token").notNull().unique(),
  platform:  varchar("platform", { length: 10 }).notNull(),
  createdAt: timestamp("created_at").defaultNow().notNull(),
  updatedAt: timestamp("updated_at").defaultNow().notNull(),
}, (t) => ({
  userIdIdx: index("push_tokens_user_id_idx").on(t.userId),
}));

// email_verifications
export const emailVerifications = pgTable("email_verifications", {
  id:        uuid("id").primaryKey().defaultRandom(),
  userId:    uuid("user_id").notNull().references(() => users.id, { onDelete: "cascade" }),
  tokenHash: text("token_hash").notNull(),
  expiresAt: timestamp("expires_at").notNull(),
  usedAt:    timestamp("used_at"),
  createdAt: timestamp("created_at").defaultNow().notNull(),
}, (t) => ({
  userIdIdx:    index("ev_user_id_idx").on(t.userId),
  tokenHashIdx: index("ev_token_hash_idx").on(t.tokenHash),
  expiryIdx:    index("ev_expires_at_idx").on(t.expiresAt),
}));

// password_reset_tokens
export const passwordResetTokens = pgTable("password_reset_tokens", {
  id:        uuid("id").primaryKey().defaultRandom(),
  userId:    uuid("user_id").notNull().references(() => users.id, { onDelete: "cascade" }),
  tokenHash: text("token_hash").notNull(),
  expiresAt: timestamp("expires_at").notNull(),
  usedAt:    timestamp("used_at"),
  createdAt: timestamp("created_at").defaultNow().notNull(),
}, (t) => ({
  userIdIdx:    index("prt_user_id_idx").on(t.userId),
  tokenHashIdx: index("prt_token_hash_idx").on(t.tokenHash),
  expiryIdx:    index("prt_expires_at_idx").on(t.expiresAt),
}));

// user_settings
export const userSettings = pgTable("user_settings", {
  userId:        uuid("user_id").primaryKey().references(() => users.id, { onDelete: "cascade" }),
  notifications: jsonb("notifications").default({}).notNull(),
  privacy:       jsonb("privacy").default({}).notNull(),
  appearance:    jsonb("appearance").default({}).notNull(),
  updatedAt:     timestamp("updated_at").defaultNow().notNull(),
});

// oauth_integrations — Phase 3
// One row per connected external provider per user.
// NOT for login — for feature integrations (email reading, etc.)
// syncState: { historyId: string } for Gmail, { deltaToken: string } for Outlook
// Empty on first connect — populated after initial sync completes
export const oauthIntegrations = pgTable("oauth_integrations", {
  id:                   uuid("id").primaryKey().defaultRandom(),
  userId:               uuid("user_id").notNull().references(() => users.id, { onDelete: "cascade" }),
  provider:             varchar("provider", { length: 30 }).notNull(), // gmail | outlook
  providerAccountId:    text("provider_account_id").notNull(),
  accessToken:          text("access_token"),          // AES-256 encrypted
  refreshToken:         text("refresh_token"),         // AES-256 encrypted
  accessTokenExpiresAt: timestamp("access_token_expires_at"),
  scopes:               text("scopes"),
  syncState:            jsonb("sync_state").default({}),
  webhookActive:        boolean("webhook_active").default(false).notNull(),
  webhookResourceId:    text("webhook_resource_id"),
  webhookExpiresAt:     timestamp("webhook_expires_at"), // Microsoft Graph subscriptions expire
  createdAt:            timestamp("created_at").defaultNow().notNull(),
  updatedAt:            timestamp("updated_at").defaultNow().notNull(),
}, (t) => ({
  userProviderUniq: uniqueIndex("oi_user_provider_idx").on(t.userId, t.provider),
}));

// synced_emails — Phase 3
// AI-enriched emails. Rolling window = EMAIL_SYNC_WINDOW_DAYS (default 90 days).
// body_text NOT stored. Full body fetched on-demand via GET /emails/:id/body.
// keywords + summary are AI-generated, unmasked before storage.
// marketing + spam never reach this table — discarded in pipeline before insert.
// GIN index on keywords added in migration SQL (not expressible in Drizzle table definition).
export const syncedEmails = pgTable("synced_emails", {
  id:                   uuid("id").primaryKey().defaultRandom(),
  userId:               uuid("user_id").notNull().references(() => users.id, { onDelete: "cascade" }),
  provider:             varchar("provider", { length: 20 }).notNull(),     // gmail | outlook
  providerMessageId:    text("provider_message_id").notNull(),
  threadId:             text("thread_id"),
  fromEmail:            varchar("from_email", { length: 255 }),
  fromName:             varchar("from_name", { length: 255 }),
  to:                   jsonb("to").default([]),                           // [{email, name}]
  cc:                   jsonb("cc").default([]),
  subject:              text("subject"),
  snippet:              text("snippet"),                                   // first 150 chars for list UI
  summary:              text("summary"),                                   // AI generated 1-2 sentences
  keywords:             jsonb("keywords").default([]),                     // AI generated, unmasked strings
  category:             varchar("category", { length: 30 }),
  // category: transactional | informational | action_required | urgent
  priorityScore:        integer("priority_score"),                        // 1–10, AI generated
  isRead:               boolean("is_read").default(false).notNull(),
  isStarred:            boolean("is_starred").default(false).notNull(),
  hasAttachments:       boolean("has_attachments").default(false).notNull(),
  attachmentMeta:       jsonb("attachment_meta").default([]),             // [{filename, size, mimeType}]
  labels:               jsonb("labels").default([]),
  aiProcessed:          boolean("ai_processed").default(false).notNull(),
  aiRetryCount:         integer("ai_retry_count").default(0).notNull(),   // hard stop at 3
  agentDelivered:       boolean("agent_delivered").default(false).notNull(),
  notificationFallback: boolean("notification_fallback").default(false).notNull(),
  receivedAt:           timestamp("received_at").notNull(),
  syncedAt:             timestamp("synced_at").defaultNow().notNull(),
  updatedAt:            timestamp("updated_at").defaultNow().notNull(),
  createdAt:            timestamp("created_at").defaultNow().notNull(),
}, (t) => ({
  userIdIdx:         index("se_user_id_idx").on(t.userId),
  providerMsgUniq:   uniqueIndex("se_provider_msg_uniq").on(t.userId, t.provider, t.providerMessageId),
  fromEmailIdx:      index("se_from_email_idx").on(t.fromEmail),
  fromNameIdx:       index("se_from_name_idx").on(t.fromName),
  subjectIdx:        index("se_subject_idx").on(t.subject),
  receivedAtIdx:     index("se_received_at_idx").on(t.receivedAt),
  isReadIdx:         index("se_is_read_idx").on(t.isRead),
  isStarredIdx:      index("se_is_starred_idx").on(t.isStarred),
  categoryIdx:       index("se_category_idx").on(t.category),
  aiProcessedIdx:    index("se_ai_processed_idx").on(t.aiProcessed),
  threadIdIdx:       index("se_thread_id_idx").on(t.threadId),
  // GIN index for keywords jsonb array added in migration SQL:
  // CREATE INDEX se_keywords_gin_idx ON synced_emails USING GIN (keywords);
}));
```

---

## Cache Layer

All caching goes through `core/redis/helpers.ts`. No module imports Redis client directly.

### `core/redis/keys.ts`

```typescript
export const RedisKeys = {
  // Phase 1
  tokenBlocklist:        (jti: string)                      => `blocklist:${jti}`,
  refreshToken:          (sessionId: string)                => `refresh:${sessionId}`,
  rateLimitIP:           (ip: string)                       => `rl:ip:${ip}`,
  rateLimitUser:         (userId: string)                   => `rl:user:${userId}`,
  passwordReset:         (token: string)                    => `reset:${token}`,
  emailVerification:     (token: string)                    => `verify:${token}`,
  userProfile:           (userId: string)                   => `user:${userId}:profile`,
  userSessions:          (userId: string)                   => `user:${userId}:sessions`,
  // Phase 2
  userSettings:          (userId: string)                   => `user:${userId}:settings`,
  // Phase 3
  emailSyncLock:         (userId: string, provider: string) => `sync:lock:${userId}:${provider}`,
  integrationOAuthState: (state: string)                    => `integration:state:${state}`,
};

export const RedisTTL = {
  // Phase 1
  accessToken:       15 * 60,
  refreshToken:      90 * 24 * 60 * 60,
  passwordReset:     15 * 60,
  emailVerification: 24 * 60 * 60,
  userProfile:       5 * 60,
  userSessions:      2 * 60,
  // Phase 2
  userSettings:      5 * 60,
  // Phase 3
  emailSyncLock:     5 * 60,   // 5 min — just long enough to cover one sync run
  oauthState:        10 * 60,  // 10 min — state param for OAuth connect flow
};
```

### `core/redis/helpers.ts`

```typescript
export const cache = {
  get:        async <T>(key: string): Promise<T | null>,
  set:        async (key: string, value: unknown, ttlSeconds: number): Promise<void>,
  del:        async (...keys: string[]): Promise<void>,
  remember:   async <T>(key: string, ttlSeconds: number, fetchFn: () => Promise<T>): Promise<T>,
  invalidate: async (...keys: string[]): Promise<void>,
};
```

---

## Middleware Stack Order

```
requestLogger
cors
helmet
json body parser
global rateLimiter
/api/v1  →  routes/index.ts
errorHandler  ← must be last
```

Per protected route:
```
authenticate → requireScopes([...]) → validate.body/params/query(schema) → controller
```

---

## Google Sign-In Flow

```
Client → Google SDK → id_token
POST /api/v1/auth/google { id_token }
  → verify with google-auth-library
  → found google identity:             login, create session, return tokens
  → email exists, no google identity:  link identity, mark verified, create session, return tokens
  → not found:                         create user + identity (isVerified=true), create session, return tokens
```

---

## OAuth Integration Connect Flow (Phase 3)

Same pattern for Gmail and Outlook:

```
1. GET /integrations/gmail/connect  (authenticated)
   → generate cryptographically random state string
   → store in Redis: RedisKeys.integrationOAuthState(state) → { userId }  TTL: 10 min
   → redirect to provider OAuth consent URL with state param

2. User approves on provider consent screen

3. GET /integrations/gmail/callback  (no auth — state verified instead)
   → read state param from query
   → look up Redis: integrationOAuthState(state) → get userId
   → if not found or expired: return 400 INVALID_STATE
   → delete state key from Redis immediately (one-time use)
   → exchange code for access_token + refresh_token
   → encrypt both tokens with AES-256
   → upsert into oauth_integrations for this userId + provider
   → trigger initial sync (fetch emails up to EMAIL_SYNC_WINDOW_DAYS back)
   → set initial historyId / deltaToken in syncState
   → redirect to client app deep link or return JSON
```

---

## Environment Variables

```bash
# App
NODE_ENV=
PORT=3001
APP_URL=
PASSWORD_RESET_URL=

# Database
DATABASE_URL=
DATABASE_SSL_ENABLED=false
DATABASE_AUTO_MIGRATE=true

# Redis
REDIS_URL=

# JWT (RS256)
JWT_PRIVATE_KEY=
JWT_PUBLIC_KEY=
JWT_ACCESS_EXPIRY=15m
JWT_REFRESH_EXPIRY=90d

# Email (SMTP)
SMTP_HOST=
SMTP_PORT=
SMTP_USER=
SMTP_PASS=
FROM_EMAIL=

# CORS
ALLOWED_ORIGINS=

# Google Sign-In — Phase 1
GOOGLE_CLIENT_ID=

# Avatar storage — Phase 2
SUPABASE_URL=
SUPABASE_SERVICE_ROLE_KEY=
SUPABASE_STORAGE_BUCKET=avatars
SUPABASE_STORAGE_PUBLIC_URL=

# Encryption for OAuth tokens at rest — Phase 3
ENCRYPTION_KEY=

# Server 2 communication — Phase 3
SERVER2_INTERNAL_URL=              # base URL of Server 2 e.g. https://server2.yourdomain.com
# No service token env var needed — service JWT signed with existing JWT_PRIVATE_KEY

# Email pipeline — Phase 3
EMAIL_SYNC_WINDOW_DAYS=90          # rolling window; emails older than this deleted by cleanOldEmails cron
EMAIL_AI_CLASSIFY_TIMEOUT_MS=3000  # hard timeout per attempt for AI classify call
EMAIL_NOTIFY_TIMEOUT_MS=2000       # hard timeout per attempt for Server 2 notify call
EMAIL_POLL_INTERVAL_MINUTES=3      # integer; code converts to cron expression: */N * * * *

# Integration providers — Phase 3
GOOGLE_CLIENT_SECRET=
GOOGLE_REDIRECT_URI=
MICROSOFT_CLIENT_ID=
MICROSOFT_CLIENT_SECRET=
MICROSOFT_REDIRECT_URI=
MICROSOFT_TENANT_ID=

# Push providers — Phase 4
APNS_KEY_ID=
APNS_TEAM_ID=
APNS_KEY_PATH=
APNS_BUNDLE_ID=
FCM_SERVICE_ACCOUNT_PATH=
```

---

## Packages

```bash
# Core
npm i express cors helmet express-rate-limit zod dotenv

# Database
npm i drizzle-orm postgres
npm i -D drizzle-kit

# Cache
npm i redis

# Auth
npm i jsonwebtoken bcryptjs
npm i google-auth-library
npm i mailchecker

# Rate limiting
npm i rate-limit-redis

# Cron
npm i node-cron
npm i -D @types/node-cron

# Email (SMTP)
npm i nodemailer
npm i -D @types/nodemailer

# Logging
npm i pino pino-http pino-pretty

# Avatar upload — Phase 2
npm i @supabase/supabase-js multer
npm i -D @types/multer

# Integration providers — Phase 3
npm i googleapis                    # Gmail API
npm i @microsoft/microsoft-graph-client   # Outlook / Graph API reads
npm i @azure/msal-node              # Microsoft user OAuth 2.0 authorization code flow

# Dev
npm i -D typescript tsx
npm i -D @types/node @types/express @types/cors @types/jsonwebtoken
```

No `axios` — all HTTP calls (Server 2 internal calls) use native `fetch` with `AbortController` for timeout.

---

## Design Rules

1. **Controller → Service → DB.** Never skip a layer.
2. **All env vars validated at startup.** Missing required var = server refuses to start.
3. **All Redis keys from `RedisKeys.*` only.** All TTLs from `RedisTTL.*` only.
4. **All caching through `cache.*`.** No module imports Redis client directly.
5. **Cache-aside on reads, invalidate on writes.**
6. **All errors thrown as `AppError` subclasses.**
7. **Refresh token rotation on every use.** Reuse = full session family revoked.
8. **Rate limit all brute-forceable endpoints.**
9. **`push_tokens.sessionId` informational only** — no FK cascade.
10. **`user_identities` is the only place auth provider logic lives.**
11. **`user_settings` created inside registration transaction.** Never upsert.
12. **OAuth provider tokens AES-256 encrypted at rest.** Never plain text.
13. **Disposable emails rejected at registration.**
14. **Avatars in Supabase Storage only.** Server stores URL string only.
15. **`processIncomingEmail()` is the single pipeline function.** Called by cron and webhook. Never duplicated.
16. **AI classify call: 3s timeout, max 3 attempts, backoff 2s/4s.** On all failures: save with `ai_processed=false`, `category='informational'`.
17. **Server 2 notify call: 2s timeout, max 3 attempts, backoff 1s/2s.** On all failures: treat as `handled=false`, fire push notification.
18. **`aiRetryCount` hard stops at 3.** `retryFailedAiProcessing` cron queries `WHERE ai_processed=false AND ai_retry_count < 3` only. No infinite loops possible.
19. **Marketing and spam discarded before any DB write.** Never stored, never logged with user PII.
20. **Sync lock per `(userId, provider)` in Redis, TTL 5 min.** If `POST /sync` called while lock active: return `202 Accepted`, do not error.
21. **First connect = initial sync. After that, delta only.** On first connect `syncState` is empty — fetch emails back to `EMAIL_SYNC_WINDOW_DAYS`, set initial `historyId`/`deltaToken`. All subsequent syncs use delta.
22. **`body_text` never stored.** Full body fetched on-demand from provider via `GET /emails/:id/body`.
23. **Masking map held in memory only.** Never written to Redis or DB. Discarded immediately after step 5 of pipeline.
24. **Batch processing uses `Promise.allSettled`.** One email failure never blocks the rest.
25. **Dedup: catch PostgreSQL error code `23505` specifically.** Treat as silent skip. Never increment `aiRetryCount` on a duplicate.
26. **`retryFailedAiProcessing` must re-fetch raw email from provider** using stored `provider_message_id` before re-masking and re-calling AI. The original masking map is gone.
27. **`cleanOldEmails` exempts starred emails.** Query: `WHERE is_starred = false AND received_at < cutoff`.
28. **`PATCH /read` and `PATCH /star` provider failures: keep DB update, log error.** Next delta sync reconciles with provider state. Never roll back the DB update on provider failure.
29. **Service JWT for Server 2 signed with existing `JWT_PRIVATE_KEY`.** Payload: `{ scope: 'internal', iss: 'server1' }`. No expiry. No extra env var.
30. **OAuth connect state param is one-time use.** Delete from Redis immediately on successful callback before exchanging the code.

---

## Phase 1 — Implementation Notes (complete)

- Refresh tokens: opaque `<sessionId>.<secret>`, bcrypt-hashed in DB, compact metadata in Redis.
- Refresh rotation: stale token = all user sessions revoked.
- Access tokens: RS256 JWT. Logout blocklists `jti` in Redis.
- Startup fails if JWT keys are malformed.
- Reset + verification tokens: random opaque values, SHA-256 hashed in DB, short-TTL metadata in Redis.
- Registration rejects disposable emails: `422 DISPOSABLE_EMAIL`.
- Unverified login: `403 EMAIL_NOT_VERIFIED`, attempts resend.
- `GOOGLE_CLIENT_ID` comma-separated for multi-audience.
- Auto-migration on startup unless `DATABASE_AUTO_MIGRATE=false`.
- Push tokens owned by `user_id`, `session_id` informational only.
- `GET /api/v1/health` implemented.
- Verified: `npm run typecheck` and `npm run build` pass.

---

## Phases

### Phase 1 — Auth foundation ✅ complete

- [x] Project scaffold
- [x] `core/config`
- [x] `core/db` — Phase 1 schemas + migrations
- [x] `core/redis` — client, keys, helpers
- [x] `core/errors`
- [x] `core/utils`
- [x] `core/middleware`
- [x] `core/types`
- [x] `modules/auth`
- [x] `modules/sessions`
- [x] `modules/notifications` — push token only
- [x] `cron/jobs/cleanExpiredTokens`
- [x] `app.ts` + `server.ts` + `routes/index.ts`

### Phase 2 — User profile & settings ✅ complete

- [x] `core/db/schema/settings.ts` + migration
- [x] `modules/users`
- [x] `modules/settings`
- [x] Registration creates `user_settings` row
- [x] `core/utils/storage.ts` — Supabase Storage

### Phase 3 — External integrations ← current

- [ ] `core/db/schema/oauth-integrations.ts` + migration
- [ ] `core/db/schema/synced-emails.ts` + migration (include GIN index SQL for keywords)
- [ ] Update `core/db/schema/index.ts` re-exports
- [ ] `core/redis/keys.ts` — add `emailSyncLock` + `integrationOAuthState` + TTLs
- [ ] `modules/integrations/shared/email.types.ts`
- [ ] `modules/integrations/shared/provider.interface.ts` — IEmailProvider interface
- [ ] `modules/integrations/shared/email.normalizer.ts`
- [ ] `modules/integrations/shared/email.masker.ts` — in-memory mask/unmask only
- [ ] `modules/integrations/shared/email.pipeline.ts` — `processIncomingEmail()`
- [ ] `modules/integrations/gmail/gmail.types.ts`
- [ ] `modules/integrations/gmail/gmail.provider.ts` — historyId delta, initial sync on first connect
- [ ] `modules/integrations/gmail/gmail.service.ts` — OAuth connect flow with state→Redis pattern
- [ ] `modules/integrations/gmail/gmail.controller.ts`
- [ ] `modules/integrations/gmail/gmail.router.ts`
- [ ] `modules/integrations/gmail/gmail.webhook.ts` — Pub/Sub stub
- [ ] `modules/integrations/outlook/outlook.types.ts`
- [ ] `modules/integrations/outlook/outlook.provider.ts` — deltaToken, initial sync on first connect
- [ ] `modules/integrations/outlook/outlook.service.ts` — OAuth connect flow with state→Redis pattern
- [ ] `modules/integrations/outlook/outlook.controller.ts`
- [ ] `modules/integrations/outlook/outlook.router.ts`
- [ ] `modules/integrations/outlook/outlook.webhook.ts` — Graph change notification stub
- [ ] `modules/integrations/integrations.types.ts`
- [ ] `modules/integrations/integrations.service.ts`
- [ ] `modules/integrations/integrations.controller.ts`
- [ ] `modules/integrations/integrations.router.ts`
- [ ] `modules/emails/emails.types.ts`
- [ ] `modules/emails/emails.validators.ts`
- [ ] `modules/emails/emails.service.ts` — search, getById, getBody, syncNow (202 if locked), markRead, markStar
- [ ] `modules/emails/emails.controller.ts`
- [ ] `modules/emails/emails.router.ts`
- [ ] `cron/jobs/syncEmails.ts` — staggered, users without webhooks, batches of 5, respects sync lock
- [ ] `cron/jobs/refreshOAuthTokens.ts` — refresh before expiry
- [ ] `cron/jobs/retryFailedAiProcessing.ts` — re-fetch raw email, re-mask, retry AI, `ai_retry_count < 3`
- [ ] `cron/jobs/cleanOldEmails.ts` — delete `WHERE is_starred=false AND received_at < cutoff`
- [ ] Update `cron/cron.bootstrap.ts` — register 4 new jobs, convert `EMAIL_POLL_INTERVAL_MINUTES` to cron expression `*/N * * * *`
- [ ] Update `routes/index.ts` — mount integrations + emails routers
- [ ] Update `.env.example` with all Phase 3 vars

### Phase 4 — Push notification dispatch

- [ ] `modules/notifications/apns.provider.ts`
- [ ] `modules/notifications/fcm.provider.ts`
- [ ] `modules/notifications/notifications.service.ts` — full dispatch called when `handled=false`

### Phase 5 — Server 2 handshake

- [ ] Share RS256 public key with Server 2
- [ ] Confirm Redis blocklist works across both servers
- [ ] Service JWT (`scope: 'internal'`) verified on Server 2 internal middleware

---

*When a phase completes: update status markers in folder structure, tick off items above, then start next phase.*