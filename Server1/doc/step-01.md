# Step 01 — Project scaffold + core infra

**Status:** ✅ done  
**Depends on:** nothing  
**Estimated effort:** 1–2 days  
**Owner:** you

---

## Goal

Stand up the smallest possible version of Server 1 that:

1. Boots an Express app via `server.ts` with graceful shutdown.
2. Connects to Postgres (Drizzle) and Redis on startup; refuses to start if DB is unreachable.
3. Runs auto-migrations when `DATABASE_AUTO_MIGRATE=true`.
4. Exposes `GET /api/v1/health`.
5. Applies the full middleware stack in the correct order (logger → CORS → helmet → JSON → rate limit → routes → error handler).

**There is no auth, no user modules, and no integrations in this step.** This step is purely the spine every later module plugs into.

---

## Files this step created

```
Server1/
├── package.json
├── tsconfig.json
├── drizzle.config.ts
├── .env.example
├── .gitignore
├── src/
│   ├── server.ts                          NEW — boot, migrate, redis connect, cron bootstrap, listen
│   ├── app.ts                             NEW — Express app + middleware stack
│   ├── routes/
│   │   └── index.ts                       NEW — health route only at this step
│   └── core/
│       ├── config/
│       │   ├── index.ts                   NEW — Zod env schema, fail-fast validation
│       │   ├── app.ts                     NEW — port, CORS, rate limit config
│       │   └── jwt.ts                     NEW — JWT key loading (RS256 PEM pair)
│       ├── db/
│       │   ├── index.ts                   NEW — postgres client, migrate runner, verify connection
│       │   └── schema/                    NEW — Drizzle schema folder (Phase 1 tables added in Step 2)
│       ├── redis/
│       │   ├── index.ts                   NEW — node-redis client + connect
│       │   ├── keys.ts                    NEW — key naming conventions + TTL constants
│       │   └── helpers.ts                 NEW — cache helpers (remember, etc.)
│       ├── errors/
│       │   ├── AppError.ts                NEW
│       │   ├── AuthError.ts               NEW
│       │   ├── ValidationError.ts         NEW
│       │   ├── NotFoundError.ts           NEW
│       │   └── index.ts                   NEW
│       ├── middleware/
│       │   ├── authenticate.ts            NEW — JWT verify stub wired in Step 2
│       │   ├── requireScopes.ts           NEW
│       │   ├── rateLimiter.ts             NEW — express-rate-limit + Redis store
│       │   ├── validate.ts                NEW — Zod body/query factory
│       │   ├── requestLogger.ts           NEW — pino-http
│       │   └── errorHandler.ts            NEW — maps AppError → JSON response
│       ├── utils/
│       │   ├── logger.ts                  NEW — Pino setup
│       │   ├── crypto.ts                  NEW — hashing helpers
│       │   ├── jwt.ts                     NEW — sign/verify access tokens
│       │   ├── pagination.ts              NEW
│       │   └── date.ts                    NEW
│       └── types/
│           ├── express.d.ts               NEW — Request user augmentation
│           └── index.ts                   NEW
```

---

## Implementation summary

### Boot sequence (`server.ts`)

1. `verifyDatabaseConnection()` — ping Postgres.
2. `runDatabaseMigrations()` — apply Drizzle SQL migrations unless disabled.
3. `redis.connect()` — connect Redis client.
4. `bootstrapCron()` — register cron jobs (Step 3 adds first job).
5. `server.listen(PORT)` — start HTTP server.
6. SIGTERM/SIGINT → graceful shutdown (close HTTP, quit Redis).

### Middleware order (`app.ts`)

```
requestLogger → cors → helmet → express.json → rateLimiter → /api/v1 routes → errorHandler
```

### Config

- Zod-validated env in `core/config/index.ts`: `DATABASE_URL`, `REDIS_URL`, `JWT_PRIVATE_KEY`, `JWT_PUBLIC_KEY`, `PORT`, `NODE_ENV`, etc.
- Startup fails if JWT PEM keys are malformed.
- `DATABASE_AUTO_MIGRATE` defaults to `true`.

### Health check

- `GET /api/v1/health` → `{ status: "ok" }` (no auth).

---

## Acceptance test (passed)

1. **`npm run typecheck`** — zero errors.
2. **`npm run build`** — compiles to `dist/`.
3. **`npm run dev`** — server starts, connects to Postgres + Redis.
4. **`curl localhost:3001/api/v1/health`** — returns `{ "status": "ok" }`.
5. Missing/invalid `JWT_PRIVATE_KEY` or `JWT_PUBLIC_KEY` → process exits on boot.

---

## Out of scope

- Auth routes and user tables (Step 2).
- Sessions, push tokens (Step 3).
- User profile, settings (Step 4).
- Email integrations (Step 5+).

---

## Notes for the next step

Step 2 adds Phase 1 DB schemas + migration `0001_phase1_auth_foundation.sql`, the full `modules/auth` module, and wires `authenticate` middleware to real JWT verification + Redis blocklist.
