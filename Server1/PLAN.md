# Server 1 — Architecture Plan
**Version:** 1.2
**Status:** Phase 1 in progress
**Last updated:** 2026-04-29

---

## Changelog

| Version | Change |
|---|---|
| 1.2 | Added `RedisTTL` constants. Expanded cache layer with `cache.remember()` cache-aside pattern for reusability. Removed incorrect `googleOAuthState` from Phase 1 Redis keys (id_token flow needs no state). Added DB indexes on all FK + lookup columns. Added `node-cron` and `mailchecker` to packages. Added `APP_URL` env var. Replaced `validateBody` with generic `validate` factory (body/params/query). Added `NotFoundError`. Clarified `DELETE /push-token` uses token in request body. Added caching design rule. |
| 1.1 | Added Google Sign-In to Phase 1. Added `user_identities` table for scalable multi-provider auth. Added email verification flow + table. Fixed `push_tokens` session cascade. Added `updated_at` to sessions. |
| 1.0 | Initial plan |

---

## Stack

- **Runtime:** Node.js + TypeScript
- **Framework:** Express.js
- **ORM:** Drizzle ORM
- **Database:** PostgreSQL
- **Cache / Session store:** Redis (ioredis)
- **JWT algorithm:** RS256 (asymmetric — private key signs, public key verifies)
- **Validation:** Zod
- **Logger:** Pino

---

## Auth Rules

- Email + password registration accepted for all real providers (Gmail, Outlook, edu, corporate, etc.)
- Temporary / disposable emails rejected at registration (via `mailchecker`)
- Google Sign-In supported at registration and login — same endpoint, find or create account
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

## Folder Structure

```
server1/
│
├── src/
│   │
│   ├── core/                              # Shared infrastructure — zero business logic
│   │   ├── db/
│   │   │   ├── index.ts                   # ⬜ Drizzle client singleton
│   │   │   ├── schema/
│   │   │   │   ├── users.ts               # ⬜
│   │   │   │   ├── user-identities.ts     # ⬜ one row per auth provider per user
│   │   │   │   ├── sessions.ts            # ⬜
│   │   │   │   ├── push-tokens.ts         # ⬜
│   │   │   │   ├── email-verifications.ts # ⬜
│   │   │   │   ├── password-reset-tokens.ts # ⬜
│   │   │   │   ├── settings.ts            # ⬜ Phase 2
│   │   │   │   ├── oauth-integrations.ts  # ⬜ Phase 3
│   │   │   │   └── index.ts               # ⬜ re-exports all schemas
│   │   │   └── migrations/                # Plain SQL files
│   │   │
│   │   ├── redis/
│   │   │   ├── index.ts                   # ⬜ Redis client singleton (ioredis)
│   │   │   ├── keys.ts                    # ⬜ RedisKeys + RedisTTL constants — only file allowed to define key strings
│   │   │   └── helpers.ts                 # ⬜ cache object — reusable caching interface for all modules
│   │   │
│   │   ├── config/
│   │   │   ├── index.ts                   # ⬜ loads + validates all env vars (zod) — server refuses to start if any required var is missing
│   │   │   ├── jwt.ts                     # ⬜ keys, expiry, algorithm
│   │   │   └── app.ts                     # ⬜ port, cors, rate limit config
│   │   │
│   │   ├── middleware/
│   │   │   ├── authenticate.ts            # ⬜ verifies access token, checks Redis blocklist, attaches req.user + req.session
│   │   │   ├── requireScopes.ts           # ⬜ scope-based auth factory
│   │   │   ├── rateLimiter.ts             # ⬜ Redis-backed per-route rate limiting factory
│   │   │   ├── validate.ts                # ⬜ Zod validation factory — validate.body() / validate.params() / validate.query()
│   │   │   ├── requestLogger.ts           # ⬜ structured request logging (Pino)
│   │   │   └── errorHandler.ts            # ⬜ global error handler — must be last middleware
│   │   │
│   │   ├── errors/
│   │   │   ├── AppError.ts                # ⬜ base error class (statusCode, code, message)
│   │   │   ├── AuthError.ts               # ⬜ 401 / 403
│   │   │   ├── ValidationError.ts         # ⬜ 422
│   │   │   ├── NotFoundError.ts           # ⬜ 404
│   │   │   └── index.ts                   # ⬜ re-exports all error classes
│   │   │
│   │   ├── utils/
│   │   │   ├── crypto.ts                  # ⬜ hash, compare, encrypt, decrypt (AES-256 + bcrypt)
│   │   │   ├── jwt.ts                     # ⬜ sign, verify, decode — wraps jsonwebtoken with app config
│   │   │   ├── pagination.ts              # ⬜ cursor + offset pagination helpers
│   │   │   ├── date.ts                    # ⬜ date formatting / add-duration helpers
│   │   │   └── logger.ts                  # ⬜ Pino logger instance — import this everywhere, not console.log
│   │   │
│   │   └── types/
│   │       ├── express.d.ts               # ⬜ augments Express Request: req.user, req.session
│   │       └── index.ts                   # ⬜ shared types used across modules (DeviceType, TokenPayload, etc.)
│   │
│   ├── modules/
│   │   │
│   │   ├── auth/                          # Phase 1
│   │   │   ├── auth.router.ts             # ⬜
│   │   │   ├── auth.controller.ts         # ⬜
│   │   │   ├── auth.service.ts            # ⬜
│   │   │   ├── auth.validators.ts         # ⬜ Zod schemas for all auth request shapes
│   │   │   ├── auth.types.ts              # ⬜
│   │   │   └── auth.helpers.ts            # ⬜ token pair generation, cookie helpers
│   │   │
│   │   ├── sessions/                      # Phase 1
│   │   │   ├── sessions.router.ts         # ⬜
│   │   │   ├── sessions.controller.ts     # ⬜
│   │   │   ├── sessions.service.ts        # ⬜ list, revoke one, revoke all others
│   │   │   └── sessions.types.ts          # ⬜
│   │   │
│   │   ├── users/                         # Phase 2
│   │   │   ├── users.router.ts            # ⬜
│   │   │   ├── users.controller.ts        # ⬜
│   │   │   ├── users.service.ts           # ⬜ profile, avatar, account deletion
│   │   │   ├── users.validators.ts        # ⬜
│   │   │   └── users.types.ts             # ⬜
│   │   │
│   │   ├── settings/                      # Phase 2
│   │   │   ├── settings.router.ts         # ⬜
│   │   │   ├── settings.controller.ts     # ⬜
│   │   │   ├── settings.service.ts        # ⬜
│   │   │   ├── settings.validators.ts     # ⬜
│   │   │   └── settings.types.ts          # ⬜
│   │   │
│   │   ├── integrations/                  # Phase 3
│   │   │   └── [sub-modules added per provider in Phase 3]
│   │   │
│   │   ├── notifications/                 # Phase 1 partial · Phase 4 full
│   │   │   ├── notifications.router.ts    # ⬜ Phase 1 — push token register/remove only
│   │   │   ├── notifications.controller.ts # ⬜
│   │   │   ├── notifications.service.ts   # ⬜
│   │   │   ├── apns.provider.ts           # ⬜ Phase 4
│   │   │   ├── fcm.provider.ts            # ⬜ Phase 4
│   │   │   └── notifications.types.ts     # ⬜
│   │   │
│   │   └── cron/                          # Phase 1 partial · grows each phase
│   │       ├── cron.bootstrap.ts          # ⬜ registers all jobs on server start
│   │       ├── jobs/
│   │       │   └── cleanExpiredTokens.ts  # ⬜ Phase 1 — purges expired sessions + reset tokens
│   │       └── cron.types.ts              # ⬜
│   │
│   ├── routes/
│   │   └── index.ts                       # ⬜ mounts all module routers under /api/v1
│   │
│   └── app.ts                             # ⬜ Express app setup + middleware stack
│
├── server.ts                              # ⬜ HTTP server entry point — starts app + cron
├── .env.example                           # ⬜
├── drizzle.config.ts                      # ⬜
├── tsconfig.json                          # ⬜
└── package.json                           # ⬜
```

**Status key:** ✅ done · 🔄 in progress · ⚠️ partial · ⬜ not started

---

## API Routes

### Phase 1 — Auth · `/api/v1/auth`

| Method | Route | Protected | Notes | Status |
|---|---|---|---|---|
| POST | `/register` | No | Email + password | ⬜ |
| POST | `/login` | No | Email + password | ⬜ |
| POST | `/google` | No | Google Sign-In — receives `id_token` from client SDK | ⬜ |
| GET | `/verify-email` | No | `?token=` from email link | ⬜ |
| POST | `/verify-email/resend` | Yes | Resend to the authenticated user's email | ⬜ |
| POST | `/token/refresh` | No | Body: `{ refresh_token }` — silent re-auth for mobile | ⬜ |
| POST | `/logout` | Yes | Revokes current session only | ⬜ |
| POST | `/logout/all` | Yes | Revokes all sessions for the user | ⬜ |
| POST | `/password/forgot` | No | Sends reset link to email | ⬜ |
| POST | `/password/reset` | No | Body: `{ token, new_password }` | ⬜ |
| POST | `/password/change` | Yes | Body: `{ current_password, new_password }` | ⬜ |
| GET | `/me` | Yes | Returns user + which identity providers are linked | ⬜ |

### Phase 1 — Sessions · `/api/v1/sessions`

| Method | Route | Protected | Notes | Status |
|---|---|---|---|---|
| GET | `/` | Yes | List all active sessions with device info | ⬜ |
| DELETE | `/:sessionId` | Yes | Revoke a specific session by ID | ⬜ |

### Phase 1 — Notifications · `/api/v1/notifications`

| Method | Route | Protected | Notes | Status |
|---|---|---|---|---|
| POST | `/push-token` | Yes | Body: `{ token, platform }` — register device push token | ⬜ |
| DELETE | `/push-token` | Yes | Body: `{ token }` — remove specific push token on logout | ⬜ |

### Phase 2 — Users · `/api/v1/users`

| Method | Route | Protected | Status |
|---|---|---|---|
| GET | `/profile` | Yes | ⬜ |
| PATCH | `/profile` | Yes | ⬜ |
| POST | `/avatar` | Yes | ⬜ |
| DELETE | `/account` | Yes | ⬜ |

### Phase 2 — Settings · `/api/v1/settings`

| Method | Route | Protected | Status |
|---|---|---|---|
| GET | `/` | Yes | ⬜ |
| PATCH | `/notifications` | Yes | ⬜ |
| PATCH | `/privacy` | Yes | ⬜ |
| PATCH | `/appearance` | Yes | ⬜ |

### Phase 3+ — Integrations · `/api/v1/integrations`
> Routes defined when Phase 3 begins.

### Phase 4+ — Push dispatch
> Additional notification routes defined when Phase 4 begins.

---

## Database Schema

### Relationship map

```
users (1) ──< user_identities (many)        — how user logs in (email, google, etc.)
users (1) ──< sessions (many)               — active login sessions per device
users (1) ──< push_tokens (many)            — APNs/FCM tokens per device
users (1) ──< email_verifications (many)    — pending verification tokens
users (1) ──< password_reset_tokens (many)  — pending reset tokens
users (1) ── user_settings (1)              — Phase 2
users (1) ──< oauth_integrations (many)     — Phase 3 — external services (mail, calendar, etc.)
```

### Design note

`users` holds only universal identity fields. Auth methods live in `user_identities` — one row per provider per user. `oauth_integrations` (Phase 3) is entirely separate: it is for connecting external services for features, not for login.

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

// user_identities — one row per auth provider per user
// provider values: 'email' | 'google' | (future: 'apple', 'github', etc.)
// For 'email': passwordHash is set, providerAccountId = user's email
// For 'google': passwordHash is null, providerAccountId = Google's user ID
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
  userIdIdx: index("sessions_user_id_idx").on(t.userId),
}));

// push_tokens
// sessionId is nullable with no FK cascade — push token belongs to the user/device
// not the session. Token must survive re-authentication on the same device.
export const pushTokens = pgTable("push_tokens", {
  id:        uuid("id").primaryKey().defaultRandom(),
  userId:    uuid("user_id").notNull().references(() => users.id, { onDelete: "cascade" }),
  sessionId: uuid("session_id"),             // nullable — informational only, no FK cascade
  token:     text("token").notNull().unique(),
  platform:  varchar("platform", { length: 10 }).notNull(), // ios | android
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
  userIdIdx: index("email_verifications_user_id_idx").on(t.userId),
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
  userIdIdx: index("prt_user_id_idx").on(t.userId),
}));

// user_settings — Phase 2
export const userSettings = pgTable("user_settings", {
  userId:        uuid("user_id").primaryKey().references(() => users.id, { onDelete: "cascade" }),
  notifications: jsonb("notifications").default({}).notNull(),
  privacy:       jsonb("privacy").default({}).notNull(),
  appearance:    jsonb("appearance").default({}).notNull(),
  updatedAt:     timestamp("updated_at").defaultNow().notNull(),
});

// oauth_integrations — Phase 3
// This is NOT login. This is connecting external services for app features.
export const oauthIntegrations = pgTable("oauth_integrations", {
  id:                   uuid("id").primaryKey().defaultRandom(),
  userId:               uuid("user_id").notNull().references(() => users.id, { onDelete: "cascade" }),
  provider:             varchar("provider", { length: 30 }).notNull(),
  providerAccountId:    text("provider_account_id").notNull(),
  accessToken:          text("access_token"),    // AES-256 encrypted at rest
  refreshToken:         text("refresh_token"),   // AES-256 encrypted at rest
  accessTokenExpiresAt: timestamp("access_token_expires_at"),
  scopes:               text("scopes"),
  createdAt:            timestamp("created_at").defaultNow().notNull(),
  updatedAt:            timestamp("updated_at").defaultNow().notNull(),
}, (t) => ({
  userProviderUniq: uniqueIndex("oi_user_provider_idx").on(t.userId, t.provider),
}));
```

---

## Cache Layer

All caching goes through `core/redis/helpers.ts`. No module imports the Redis client directly — they import the `cache` object. This makes the caching layer swappable and keeps all cache logic in one place.

### `core/redis/keys.ts`

```typescript
// All Redis key strings — never hardcode a key string outside this file
export const RedisKeys = {
  tokenBlocklist:        (jti: string)        => `blocklist:${jti}`,
  refreshToken:          (sessionId: string)  => `refresh:${sessionId}`,
  rateLimitIP:           (ip: string)         => `rl:ip:${ip}`,
  rateLimitUser:         (userId: string)     => `rl:user:${userId}`,
  passwordReset:         (token: string)      => `reset:${token}`,
  emailVerification:     (token: string)      => `verify:${token}`,
  userProfile:           (userId: string)     => `user:${userId}:profile`,
  userSessions:          (userId: string)     => `user:${userId}:sessions`,
  integrationOAuthState: (state: string)      => `integration:state:${state}`, // Phase 3
};

// All TTLs in seconds — single source of truth, never magic numbers in services
export const RedisTTL = {
  accessToken:       15 * 60,               // 15 min — matches JWT access token expiry
  refreshToken:      90 * 24 * 60 * 60,     // 90 days — matches refresh token expiry
  passwordReset:     15 * 60,               // 15 min
  emailVerification: 24 * 60 * 60,          // 24 hours
  oauthState:        10 * 60,               // 10 min — Phase 3
  userProfile:       5 * 60,                // 5 min read cache
  userSessions:      2 * 60,                // 2 min read cache
};
```

### `core/redis/helpers.ts`

```typescript
// The cache object — import this in services, never import the Redis client directly
export const cache = {

  // Read a cached value. Returns null if not found.
  get: async <T>(key: string): Promise<T | null> => { ... },

  // Write a value. ttlSeconds is required — no indefinite caching.
  set: async (key: string, value: unknown, ttlSeconds: number): Promise<void> => { ... },

  // Delete one or more keys (cache invalidation).
  del: async (...keys: string[]): Promise<void> => { ... },

  // Cache-aside pattern — the main reusable helper.
  // Tries cache first. On miss, calls fetchFn, stores result, returns it.
  // Usage: const user = await cache.remember(RedisKeys.userProfile(id), RedisTTL.userProfile, () => db.query...)
  remember: async <T>(key: string, ttlSeconds: number, fetchFn: () => Promise<T>): Promise<T> => { ... },

  // Invalidate a list of keys atomically (use after mutations).
  // Usage: await cache.invalidate(RedisKeys.userProfile(id), RedisKeys.userSessions(id))
  invalidate: async (...keys: string[]): Promise<void> => { ... },
};
```

**Caching pattern for services:**
```typescript
// Reading — wrap any DB call with cache.remember
const user = await cache.remember(
  RedisKeys.userProfile(userId),
  RedisTTL.userProfile,
  () => db.select().from(users).where(eq(users.id, userId))
);

// Writing — always invalidate affected keys after mutation
await db.update(users).set({ name }).where(eq(users.id, userId));
await cache.invalidate(RedisKeys.userProfile(userId));
```

---

## Redis Keys

See **Cache Layer** section above. All keys and TTLs live in `core/redis/keys.ts`.

---

## Middleware Stack Order

```
requestLogger
cors
helmet
json body parser
global rateLimiter (Redis-backed)
/api/v1  →  routes/index.ts
errorHandler  ← must be last
```

Per protected route:
```
authenticate → requireScopes([...]) → validate.body(schema) → controller
```

### `validate` factory

Handles body, params, and query separately so each route validates exactly what it uses:

```typescript
// Usage examples
router.post('/register',   validate.body(registerSchema),     controller.register)
router.delete('/:sessionId', validate.params(sessionIdSchema), controller.revoke)
router.get('/verify-email',  validate.query(tokenQuerySchema),  controller.verifyEmail)
```

---

## Google Sign-In Flow

The mobile app and web client use the Google SDK to get a signed `id_token`. The server verifies it with Google, then finds or creates the account. No redirect, no state param needed.

```
Client → Google SDK → receives id_token
Client → POST /api/v1/auth/google  { id_token }
Server → verifies id_token using google-auth-library
Server → extracts email + Google user ID from verified payload
Server → look up user_identity where provider='google' AND providerAccountId = googleUserId
  → Found:     log in existing user, create session, return tokens
  → Not found: create user (isVerified=true) + user_identity, create session, return tokens
```

Package: `google-auth-library` — verifies id_token against Google's public keys.

---

## Environment Variables

```bash
# App
NODE_ENV=
PORT=3001
APP_URL=                                 # base URL for email links e.g. https://yourdomain.com

# Database
DATABASE_URL=

# Redis
REDIS_URL=

# JWT (RS256)
JWT_PRIVATE_KEY=
JWT_PUBLIC_KEY=
JWT_ACCESS_EXPIRY=15m
JWT_REFRESH_EXPIRY=90d

# Email (password reset + verification)
SMTP_HOST=
SMTP_PORT=
SMTP_USER=
SMTP_PASS=
FROM_EMAIL=

# CORS
ALLOWED_ORIGINS=

# Google Sign-In — Phase 1 (id_token verification only)
GOOGLE_CLIENT_ID=

# Encryption for external tokens at rest — Phase 3
ENCRYPTION_KEY=

# Push providers — Phase 4
APNS_KEY_ID=
APNS_TEAM_ID=
APNS_KEY_PATH=
APNS_BUNDLE_ID=
FCM_SERVICE_ACCOUNT_PATH=

# Integration providers — Phase 3
GOOGLE_CLIENT_SECRET=
GOOGLE_REDIRECT_URI=
MICROSOFT_CLIENT_ID=
MICROSOFT_CLIENT_SECRET=
MICROSOFT_REDIRECT_URI=
MICROSOFT_TENANT_ID=
```

---

## Packages

```bash
# Core
npm i express cors helmet express-rate-limit zod

# Database
npm i drizzle-orm postgres
npm i -D drizzle-kit

# Cache
npm i ioredis

# Auth
npm i jsonwebtoken bcryptjs
npm i google-auth-library              # Google Sign-In id_token verification
npm i mailchecker                      # Disposable email detection

# Cron
npm i node-cron
npm i -D @types/node-cron

# Email
npm i nodemailer
npm i -D @types/nodemailer

# Logging
npm i pino pino-pretty

# Dev
npm i -D typescript tsx
npm i -D @types/node @types/express @types/jsonwebtoken @types/bcryptjs
```

---

## Design Rules

1. **Controller → Service → DB.** Never skip a layer. Controllers never touch the DB or cache directly.
2. **All env vars validated at startup** via Zod. Missing required var = server refuses to start.
3. **All Redis keys come from `RedisKeys.*` only.** All TTLs come from `RedisTTL.*` only.
4. **All caching goes through `cache.*` from `core/redis/helpers.ts`.** No module imports the Redis client directly.
5. **Cache-aside on reads, invalidate on writes.** Use `cache.remember()` for reads. Call `cache.invalidate()` after any mutation.
6. **All errors thrown as `AppError` subclasses.** Global handler formats all error responses uniformly.
7. **Refresh token rotation on every use.** Reuse of a revoked token = full session family revoked immediately.
8. **Rate limit all brute-forceable endpoints:** `/auth/login`, `/auth/token/refresh`, `/auth/password/forgot`, `/auth/google`.
9. **`push_tokens.sessionId` is informational only** — no FK cascade. Token lifetime = user lifetime, not session lifetime.
10. **`user_identities` is the only place auth provider logic lives.** `users` table never gets provider-specific columns.
11. **OAuth provider tokens (Phase 3) stored AES-256 encrypted.** Never plain text in DB.
12. **Disposable emails rejected at registration** using `mailchecker` before any DB write.

---

## Phases

### Phase 1 — Auth foundation ← current

- [ ] Project scaffold (tsconfig, drizzle.config, package.json)
- [ ] `core/config` — env validation (all vars, fail fast)
- [ ] `core/db` — client + Phase 1 schemas (users, user_identities, sessions, push_tokens, email_verifications, password_reset_tokens) + migrations
- [ ] `core/redis` — client, keys (RedisKeys + RedisTTL), helpers (cache object)
- [ ] `core/errors` — AppError, AuthError, ValidationError, NotFoundError
- [ ] `core/utils` — crypto, jwt, logger, pagination, date
- [ ] `core/middleware` — authenticate, requireScopes, rateLimiter, validate, requestLogger, errorHandler
- [ ] `core/types` — express.d.ts, index.ts
- [ ] `modules/auth` — register, login, google, verify-email, verify-email/resend, token/refresh, logout, logout/all, password/forgot, password/reset, password/change, me
- [ ] `modules/sessions` — list, revoke one, revoke all others
- [ ] `modules/notifications` — push token register + remove
- [ ] `cron/jobs/cleanExpiredTokens` — purges expired sessions + reset tokens nightly
- [ ] `app.ts` + `server.ts` + `routes/index.ts`

### Phase 2 — User profile & settings

- [ ] `core/db/schema/settings.ts` + migration
- [ ] `modules/users` — profile get/update, avatar upload, account deletion (soft delete)
- [ ] `modules/settings` — get/update notifications, privacy, appearance

### Phase 3 — External integrations

- [ ] `core/db/schema/oauth-integrations.ts` + migration
- [ ] `modules/integrations/[provider]` — one self-contained sub-module per provider
- [ ] `cron/jobs` — provider token refresh jobs

### Phase 4 — Push notification dispatch

- [ ] `modules/notifications` — APNs provider (iOS), FCM provider (Android), dispatch logic

### Phase 5 — Server 2 handshake

- [ ] Share RS256 public key with Server 2
- [ ] Confirm Redis blocklist check works across both servers
- [ ] Service-to-service internal token for Server 2 → Server 1 privileged calls

---

*When a phase completes: update status markers in folder structure, tick off items above, then start next phase.*