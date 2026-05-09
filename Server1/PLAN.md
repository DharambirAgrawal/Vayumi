# Server 1 — Architecture Plan
**Version:** 1.4
**Status:** Phase 2 in progress
**Last updated:** 2026-04-29

---

## Changelog

| Version | Change |
|---|---|
| 1.4 | Phase 1 marked complete. Fixed `notifications.types.ts` status to ✅. Added `GET /api/v1/health` to routes table. Moved `PASSWORD_RESET_URL` env var to App section. Expanded Phase 2 checklist to full file-level granularity. Defined avatar storage (S3-compatible). Defined `user_settings` row creation timing (on registration). |
| 1.3 | Implemented Phase 1. Added startup auto-migration, multi-audience Google token verification, unverified-email login blocking, public verification resend-by-email route, safer query validation. Verified with `npm run typecheck` and `npm run build`. |
| 1.2 | Added `RedisTTL` constants. Expanded cache layer with `cache.remember()`. Removed incorrect `googleOAuthState` from Phase 1 Redis keys. Added DB indexes. Added `node-cron` and `mailchecker`. Added `APP_URL` env var. Replaced `validateBody` with generic `validate` factory. Added `NotFoundError`. Clarified `DELETE /push-token` body. Added caching design rule. |
| 1.1 | Added Google Sign-In. Added `user_identities` table. Added email verification flow. Fixed `push_tokens` session cascade. Added `updated_at` to sessions. |
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

## Folder Structure

```
server1/
│
├── src/
│   │
│   ├── core/                              # Shared infrastructure — zero business logic
│   │   ├── db/
│   │   │   ├── index.ts                   # ✅ Drizzle client singleton
│   │   │   ├── schema/
│   │   │   │   ├── users.ts               # ✅
│   │   │   │   ├── user-identities.ts     # ✅ one row per auth provider per user
│   │   │   │   ├── sessions.ts            # ✅
│   │   │   │   ├── push-tokens.ts         # ✅
│   │   │   │   ├── email-verifications.ts # ✅
│   │   │   │   ├── password-reset-tokens.ts # ✅
│   │   │   │   ├── settings.ts            # ⬜ Phase 2
│   │   │   │   ├── oauth-integrations.ts  # ⬜ Phase 3
│   │   │   │   └── index.ts               # ✅ re-exports all schemas
│   │   │   └── migrations/                # ✅ Plain SQL files
│   │   │
│   │   ├── redis/
│   │   │   ├── index.ts                   # ✅ Redis client singleton (node-redis)
│   │   │   ├── keys.ts                    # ✅ RedisKeys + RedisTTL constants
│   │   │   └── helpers.ts                 # ✅ cache object — reusable caching interface for all modules
│   │   │
│   │   ├── config/
│   │   │   ├── index.ts                   # ✅ loads + validates all env vars (zod)
│   │   │   ├── jwt.ts                     # ✅ keys, expiry, algorithm
│   │   │   └── app.ts                     # ✅ port, cors, rate limit config
│   │   │
│   │   ├── middleware/
│   │   │   ├── authenticate.ts            # ✅ verifies access token, checks Redis blocklist, attaches req.auth
│   │   │   ├── requireScopes.ts           # ✅ scope-based auth factory
│   │   │   ├── rateLimiter.ts             # ✅ Redis-backed per-route rate limiting factory
│   │   │   ├── validate.ts                # ✅ Zod validation factory — validate.body() / validate.params() / validate.query()
│   │   │   ├── requestLogger.ts           # ✅ structured request logging (Pino)
│   │   │   └── errorHandler.ts            # ✅ global error handler — must be last middleware
│   │   │
│   │   ├── errors/
│   │   │   ├── AppError.ts                # ✅ base error class (statusCode, code, message)
│   │   │   ├── AuthError.ts               # ✅ 401 / 403
│   │   │   ├── ValidationError.ts         # ✅ 422
│   │   │   ├── NotFoundError.ts           # ✅ 404
│   │   │   └── index.ts                   # ✅ re-exports all error classes
│   │   │
│   │   ├── utils/
│   │   │   ├── crypto.ts                  # ✅ hash, compare, encrypt, decrypt (AES-256 + bcrypt)
│   │   │   ├── jwt.ts                     # ✅ sign, verify, decode — wraps jsonwebtoken with app config
│   │   │   ├── pagination.ts              # ✅ cursor + offset pagination helpers
│   │   │   ├── date.ts                    # ✅ date formatting / add-duration helpers
│   │   │   └── logger.ts                  # ✅ Pino logger instance
│   │   │
│   │   └── types/
│   │       ├── express.d.ts               # ✅ augments Express Request: req.auth.user, req.auth.session, req.auth.token
│   │       └── index.ts                   # ✅ shared types (DeviceType, TokenPayload, etc.)
│   │
│   ├── modules/
│   │   │
│   │   ├── auth/                          # ✅ Phase 1 complete
│   │   │   ├── auth.router.ts             # ✅
│   │   │   ├── auth.controller.ts         # ✅
│   │   │   ├── auth.service.ts            # ✅
│   │   │   ├── auth.validators.ts         # ✅
│   │   │   ├── auth.types.ts              # ✅
│   │   │   └── auth.helpers.ts            # ✅
│   │   │
│   │   ├── sessions/                      # ✅ Phase 1 complete
│   │   │   ├── sessions.router.ts         # ✅
│   │   │   ├── sessions.controller.ts     # ✅
│   │   │   ├── sessions.service.ts        # ✅
│   │   │   └── sessions.types.ts          # ✅
│   │   │
│   │   ├── users/                         # ⬜ Phase 2
│   │   │   ├── users.router.ts            # ⬜
│   │   │   ├── users.controller.ts        # ⬜
│   │   │   ├── users.service.ts           # ⬜
│   │   │   ├── users.validators.ts        # ⬜
│   │   │   └── users.types.ts             # ⬜
│   │   │
│   │   ├── settings/                      # ⬜ Phase 2
│   │   │   ├── settings.router.ts         # ⬜
│   │   │   ├── settings.controller.ts     # ⬜
│   │   │   ├── settings.service.ts        # ⬜
│   │   │   ├── settings.validators.ts     # ⬜
│   │   │   └── settings.types.ts          # ⬜
│   │   │
│   │   ├── integrations/                  # ⬜ Phase 3
│   │   │   └── [sub-modules added per provider in Phase 3]
│   │   │
│   │   ├── notifications/                 # ✅ Phase 1 partial · ⬜ Phase 4 full
│   │   │   ├── notifications.router.ts    # ✅
│   │   │   ├── notifications.controller.ts # ✅
│   │   │   ├── notifications.service.ts   # ✅
│   │   │   ├── notifications.validators.ts # ✅
│   │   │   ├── notifications.types.ts     # ✅
│   │   │   ├── apns.provider.ts           # ⬜ Phase 4
│   │   │   └── fcm.provider.ts            # ⬜ Phase 4
│   │   │
│   │   └── cron/                          # ✅ Phase 1 partial · grows each phase
│   │       ├── cron.bootstrap.ts          # ✅
│   │       ├── jobs/
│   │       │   └── cleanExpiredTokens.ts  # ✅
│   │       └── cron.types.ts              # ✅
│   │
│   ├── routes/
│   │   └── index.ts                       # ✅ mounts all module routers under /api/v1
│   │
│   └── app.ts                             # ✅ Express app setup + middleware stack
│
├── server.ts                              # ✅ HTTP server entry point
├── .env.example                           # ✅
├── drizzle.config.ts                      # ✅
├── tsconfig.json                          # ✅
└── package.json                           # ✅
```

**Status key:** ✅ done · 🔄 in progress · ⚠️ partial · ⬜ not started

---

## API Routes

### Health

| Method | Route | Protected | Notes | Status |
|---|---|---|---|---|
| GET | `/api/v1/health` | No | Service health check | ✅ |

### Phase 1 — Auth · `/api/v1/auth`

| Method | Route | Protected | Notes | Status |
|---|---|---|---|---|
| POST | `/register` | No | Email + password | ✅ |
| POST | `/login` | No | Email + password | ✅ |
| POST | `/google` | No | Receives `id_token` from client SDK | ✅ |
| GET | `/verify-email` | No | `?token=` from email link | ✅ |
| POST | `/verify-email/resend` | Yes | Resend to authenticated user's email | ✅ |
| POST | `/verify-email/resend/request` | No | Resend by email address (pre-login) | ✅ |
| POST | `/token/refresh` | No | Body: `{ refresh_token }` — silent re-auth | ✅ |
| POST | `/logout` | Yes | Revokes current session only | ✅ |
| POST | `/logout/all` | Yes | Revokes all sessions for the user | ✅ |
| POST | `/password/forgot` | No | Sends reset link to email | ✅ |
| POST | `/password/reset` | No | Body: `{ token, new_password }` | ✅ |
| POST | `/password/change` | Yes | Body: `{ current_password, new_password }` | ✅ |
| GET | `/me` | Yes | Returns user + linked identity providers | ✅ |

### Phase 1 — Sessions · `/api/v1/sessions`

| Method | Route | Protected | Notes | Status |
|---|---|---|---|---|
| GET | `/` | Yes | List all active sessions with device info | ✅ |
| DELETE | `/:sessionId` | Yes | Revoke a specific session by ID | ✅ |

### Phase 1 — Notifications · `/api/v1/notifications`

| Method | Route | Protected | Notes | Status |
|---|---|---|---|---|
| POST | `/push-token` | Yes | Body: `{ token, platform }` | ✅ |
| DELETE | `/push-token` | Yes | Body: `{ token }` | ✅ |

### Phase 2 — Users · `/api/v1/users`

| Method | Route | Protected | Notes | Status |
|---|---|---|---|---|
| GET | `/profile` | Yes | Returns user profile | ⬜ |
| PATCH | `/profile` | Yes | Body: `{ name?, avatarUrl? }` | ⬜ |
| POST | `/avatar` | Yes | Multipart upload → S3 → returns `avatarUrl` | ⬜ |
| DELETE | `/account` | Yes | Soft delete — revokes all sessions + tokens | ⬜ |

### Phase 2 — Settings · `/api/v1/settings`

| Method | Route | Protected | Notes | Status |
|---|---|---|---|---|
| GET | `/` | Yes | Returns full settings object | ⬜ |
| PATCH | `/notifications` | Yes | Partial update of notifications prefs | ⬜ |
| PATCH | `/privacy` | Yes | Partial update of privacy prefs | ⬜ |
| PATCH | `/appearance` | Yes | Partial update of appearance prefs (theme, language) | ⬜ |

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
users (1) ── user_settings (1)              — Phase 2 — created on registration
users (1) ──< oauth_integrations (many)     — Phase 3 — external services (mail, calendar, etc.)
```

### Design note

`users` holds only universal identity fields. Auth methods live in `user_identities` — one row per provider per user. `user_settings` is created as part of the registration transaction so it always exists for any user and never needs an upsert. `oauth_integrations` (Phase 3) is entirely separate: connecting external services for features, not for login.

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
// provider: 'email' | 'google' | (future: 'apple', 'github', etc.)
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
  userIdIdx:  index("sessions_user_id_idx").on(t.userId),
  expiryIdx:  index("sessions_expires_at_idx").on(t.expiresAt),
  activeIdx:  index("sessions_is_active_idx").on(t.isActive),
}));

// push_tokens
// sessionId nullable — no FK cascade. Token lifetime = user lifetime, not session lifetime.
export const pushTokens = pgTable("push_tokens", {
  id:        uuid("id").primaryKey().defaultRandom(),
  userId:    uuid("user_id").notNull().references(() => users.id, { onDelete: "cascade" }),
  sessionId: uuid("session_id"),
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
  userIdIdx:    index("email_verifications_user_id_idx").on(t.userId),
  tokenHashIdx: index("email_verifications_token_hash_idx").on(t.tokenHash),
  expiryIdx:    index("email_verifications_expires_at_idx").on(t.expiresAt),
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

// user_settings — Phase 2
// Row created inside the registration transaction — always exists for every user.
// Services use plain update, never upsert.
export const userSettings = pgTable("user_settings", {
  userId:        uuid("user_id").primaryKey().references(() => users.id, { onDelete: "cascade" }),
  notifications: jsonb("notifications").default({}).notNull(),
  privacy:       jsonb("privacy").default({}).notNull(),
  appearance:    jsonb("appearance").default({}).notNull(),
  updatedAt:     timestamp("updated_at").defaultNow().notNull(),
});

// oauth_integrations — Phase 3
// NOT login. Connecting external services for app features.
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

All caching goes through `core/redis/helpers.ts`. No module imports the Redis client directly — they import the `cache` object.

### `core/redis/keys.ts`

```typescript
export const RedisKeys = {
  tokenBlocklist:        (jti: string)       => `blocklist:${jti}`,
  refreshToken:          (sessionId: string) => `refresh:${sessionId}`,
  rateLimitIP:           (ip: string)        => `rl:ip:${ip}`,
  rateLimitUser:         (userId: string)    => `rl:user:${userId}`,
  passwordReset:         (token: string)     => `reset:${token}`,
  emailVerification:     (token: string)     => `verify:${token}`,
  userProfile:           (userId: string)    => `user:${userId}:profile`,
  userSessions:          (userId: string)    => `user:${userId}:sessions`,
  userSettings:          (userId: string)    => `user:${userId}:settings`,   // Phase 2
  integrationOAuthState: (state: string)     => `integration:state:${state}`, // Phase 3
};

export const RedisTTL = {
  accessToken:       15 * 60,
  refreshToken:      90 * 24 * 60 * 60,
  passwordReset:     15 * 60,
  emailVerification: 24 * 60 * 60,
  oauthState:        10 * 60,
  userProfile:       5 * 60,
  userSessions:      2 * 60,
  userSettings:      5 * 60,   // Phase 2
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

**Pattern — reading:**
```typescript
const user = await cache.remember(
  RedisKeys.userProfile(userId),
  RedisTTL.userProfile,
  () => db.select().from(users).where(eq(users.id, userId))
);
```

**Pattern — writing:**
```typescript
await db.update(users).set({ name }).where(eq(users.id, userId));
await cache.invalidate(RedisKeys.userProfile(userId));
```

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
authenticate → requireScopes([...]) → validate.body/params/query(schema) → controller
```

---

## Google Sign-In Flow

```
Client → Google SDK → receives id_token
Client → POST /api/v1/auth/google  { id_token }
Server → verifies id_token with google-auth-library against GOOGLE_CLIENT_ID audiences
Server → extracts email + Google user ID
  → Found by google identity:          log in, create session, return tokens
  → Not found but email exists:        link Google identity, mark verified, create session, return tokens
  → Not found at all:                  create user (isVerified=true) + identity, create session, return tokens
```

---

## Avatar Storage (Phase 2)

Avatars are uploaded to an S3-compatible bucket (AWS S3 or Cloudflare R2). The server receives the file via multipart, uploads to S3, stores only the resulting public URL in `users.avatarUrl`. The server never serves avatar files directly.

**New env vars needed for Phase 2:**
```bash
S3_BUCKET=
S3_REGION=
S3_ACCESS_KEY_ID=
S3_SECRET_ACCESS_KEY=
S3_ENDPOINT=           # leave blank for AWS; set for R2 or other S3-compatible
S3_PUBLIC_URL=         # CDN or bucket public base URL
```

**New package needed for Phase 2:**
```bash
npm i @aws-sdk/client-s3 @aws-sdk/lib-storage
npm i multer && npm i -D @types/multer   # multipart parsing
```

---

## Environment Variables

All env vars listed below are validated at startup. Phase 3/4 entries are still required by config today.

```bash
# App
NODE_ENV=
PORT=3001
APP_URL=                   # base URL for server e.g. https://api.yourdomain.com
PASSWORD_RESET_URL=        # client-side reset screen URL (app or web)

# Database
DATABASE_URL=
DATABASE_SSL_ENABLED=false
DATABASE_AUTO_MIGRATE=true

# Redis
REDIS_URL=                 # or provide REDIS_HOST/REDIS_PORT/REDIS_PASSWORD
REDIS_HOST=
REDIS_PORT=
REDIS_USERNAME=default
REDIS_PASSWORD=
REDIS_TLS_ENABLED=true

# JWT (RS256 — PEM values, use escaped \n or base64-encoded PEM)
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

# Google Sign-In — Phase 1 (comma-separated if multiple client IDs)
GOOGLE_CLIENT_ID=

# Avatar storage — Phase 2
S3_BUCKET=
S3_REGION=
S3_ACCESS_KEY_ID=
S3_SECRET_ACCESS_KEY=
S3_ENDPOINT=
S3_PUBLIC_URL=

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

# Email
npm i nodemailer
npm i -D @types/nodemailer

# Logging
npm i pino pino-http pino-pretty

# Avatar upload — Phase 2
npm i @aws-sdk/client-s3 @aws-sdk/lib-storage multer
npm i -D @types/multer

# Dev
npm i -D typescript tsx
npm i -D @types/node @types/express @types/cors @types/jsonwebtoken
```

---

## Design Rules

1. **Controller → Service → DB.** Never skip a layer. Controllers never touch DB or cache directly.
2. **All env vars validated at startup** via Zod. Missing required var = server refuses to start.
3. **All Redis keys come from `RedisKeys.*` only.** All TTLs come from `RedisTTL.*` only.
4. **All caching goes through `cache.*` from `core/redis/helpers.ts`.** No module imports Redis client directly.
5. **Cache-aside on reads, invalidate on writes.** Use `cache.remember()` for reads. Call `cache.invalidate()` after any mutation.
6. **All errors thrown as `AppError` subclasses.** Global handler formats all responses uniformly.
7. **Refresh token rotation on every use.** Reuse of revoked token = full session family revoked immediately.
8. **Rate limit all brute-forceable endpoints:** `/auth/login`, `/auth/token/refresh`, `/auth/password/forgot`, `/auth/google`.
9. **`push_tokens.sessionId` is informational only** — no FK cascade. Token lifetime = user lifetime, not session lifetime.
10. **`user_identities` is the only place auth provider logic lives.** `users` table never gets provider-specific columns.
11. **`user_settings` row is created inside the registration transaction.** Never upsert — always plain update.
12. **OAuth provider tokens (Phase 3) stored AES-256 encrypted.** Never plain text in DB.
13. **Disposable emails rejected at registration** using `mailchecker` before any DB write.
14. **Avatars stored in S3 only.** Server stores the public URL string, never serves files directly.

---

## Phase 1 — Implementation Notes (complete)

- Refresh tokens are opaque `<sessionId>.<secret>` values. The full token is bcrypt-hashed in `sessions.refresh_token_hash`; Redis stores compact session metadata under `RedisKeys.refreshToken(sessionId)`.
- Refresh token rotation happens on every refresh. Stale or mismatched token = all user sessions revoked.
- Access tokens are RS256 JWTs. Logout blocklists the `jti` in Redis until natural expiry.
- Startup fails early if JWT keys are malformed.
- Email verification and password reset tokens are random opaque values. DB stores only SHA-256 hashes; Redis stores compact metadata with short TTLs.
- Registration rejects disposable email domains with `422 DISPOSABLE_EMAIL`.
- Email/password login with unverified email returns `403 EMAIL_NOT_VERIFIED` and attempts to resend verification.
- `GOOGLE_CLIENT_ID` accepts comma-separated values so iOS, Android, and web audiences are all accepted.
- Startup applies pending SQL migrations automatically unless `DATABASE_AUTO_MIGRATE=false`.
- Push tokens owned by `user_id`; `session_id` is informational only and updated on re-registration.
- `GET /api/v1/health` implemented for service health checks.
- Verified: `npm run typecheck` and `npm run build` pass.

---

## Phases

### Phase 1 — Auth foundation ✅ complete

- [x] Project scaffold (tsconfig, drizzle.config, package.json)
- [x] `core/config` — env validation
- [x] `core/db` — client + Phase 1 schemas + migrations
- [x] `core/redis` — client, keys (RedisKeys + RedisTTL), helpers (cache object)
- [x] `core/errors` — AppError, AuthError, ValidationError, NotFoundError
- [x] `core/utils` — crypto, jwt, logger, pagination, date
- [x] `core/middleware` — authenticate, requireScopes, rateLimiter, validate, requestLogger, errorHandler
- [x] `core/types` — express.d.ts, index.ts
- [x] `modules/auth` — register, login, google, verify-email, verify-email/resend, verify-email/resend/request, token/refresh, logout, logout/all, password/forgot, password/reset, password/change, me
- [x] `modules/sessions` — list active sessions, revoke one session
- [x] `modules/notifications` — push token register + remove
- [x] `cron/jobs/cleanExpiredTokens`
- [x] `app.ts` + `server.ts` + `routes/index.ts`

### Phase 2 — User profile & settings ← current

- [ ] `core/db/schema/settings.ts` + SQL migration
- [ ] Update `core/db/schema/index.ts` to re-export settings schema
- [ ] `core/redis/keys.ts` — add `userSettings` key + TTL (already shown in plan above)
- [ ] `modules/users/users.types.ts`
- [ ] `modules/users/users.validators.ts` — profile update schema, avatar schema
- [ ] `modules/users/users.service.ts` — getProfile, updateProfile, uploadAvatar, deleteAccount
- [ ] `modules/users/users.controller.ts`
- [ ] `modules/users/users.router.ts`
- [ ] `modules/settings/settings.types.ts`
- [ ] `modules/settings/settings.validators.ts` — partial update schemas per section
- [ ] `modules/settings/settings.service.ts` — getSettings, updateNotifications, updatePrivacy, updateAppearance
- [ ] `modules/settings/settings.controller.ts`
- [ ] `modules/settings/settings.router.ts`
- [ ] Update `routes/index.ts` to mount users + settings routers
- [ ] Update registration flow to create `user_settings` row in same transaction
- [ ] Update `GET /auth/me` to include linked providers list (already in Phase 1, verify it returns provider list)
- [ ] S3 upload utility in `core/utils/storage.ts`

### Phase 3 — External integrations

- [ ] `core/db/schema/oauth-integrations.ts` + migration
- [ ] `modules/integrations/[provider]` — one self-contained sub-module per provider
- [ ] `cron/jobs` — provider token refresh jobs

### Phase 4 — Push notification dispatch

- [ ] `modules/notifications/apns.provider.ts` — iOS push
- [ ] `modules/notifications/fcm.provider.ts` — Android push
- [ ] `modules/notifications/notifications.service.ts` — full dispatch logic

### Phase 5 — Server 2 handshake

- [ ] Share RS256 public key with Server 2
- [ ] Confirm Redis blocklist check works across both servers
- [ ] Service-to-service internal token for Server 2 → Server 1 privileged calls

---

*When a phase completes: update status markers in folder structure, tick off items above, then start next phase.*