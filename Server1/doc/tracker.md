# Vayumi Server 1 — Build Tracker & Architecture Flows

> **Purpose:** One file to see (1) what's built, (2) how data moves through the system.  
> Updated after each step completes.  
> **Last updated:** 2026-06-07 — Steps 1–6 complete; Step 7 next

---

## Current build step

**Step 7** — Gmail OAuth + provider + disconnect ([`doc/step-07.md`](step-07.md))

---

## Step index (quick reference)

| Step | Name | Status | Detail doc |
|------|------|--------|------------|
| 1 | Scaffold + core infra | ✅ | [`doc/step-01.md`](step-01.md) |
| 2 | Auth module | ✅ | [`doc/step-02.md`](step-02.md) |
| 3 | Sessions + push + cron | ✅ | [`doc/step-03.md`](step-03.md) |
| 4 | Users + settings + avatar | ✅ | [`doc/step-04.md`](step-04.md) |
| 5 | Email pipeline foundation | ✅ | [`doc/step-05.md`](step-05.md) |
| 6 | Reminders & scheduled tasks | ✅ | [`doc/step-06.md`](step-06.md) |
| 7 | Gmail OAuth + provider | ⬜ | [`doc/step-07.md`](step-07.md) |
| 8 | Outlook OAuth + provider | ⬜ | — |
| 9 | Emails module | ⬜ | — |
| 10 | Cron jobs | ⬜ | — |
| 11 | Webhook stubs | ⬜ | — |
| 12 | Push dispatch | ⬜ | — |
| 13 | Server 2 handshake | ⬜ | — |

---

## Build progress

```
PHASE 1 — AUTH                    PHASE 2 — PROFILE           PHASE 3 — INTEGRATIONS
┌────────┬────────┬────────┐      ┌────────┐                 ┌────────┬────────┬────────┬────────┬────────┐
│ Step 1 │ Step 2 │ Step 3 │      │ Step 4 │                 │ Step 5 │ Step 6 │ Step 7 │ Step 8 │ Step 9 │
│Scaffold│  Auth  │Sessions│      │ Profile│                 │Pipeline│ Gmail  │Outlook │ Emails │  Cron  │
│   ✅   │   ✅   │   ✅   │      │   ✅   │                 │   ✅   │   ⬜   │   ⬜   │   ⬜   │   ⬜   │
└────────┴────────┴────────┘      └────────┘                 └────┬───┴───┬────┴───┬────┴───┬────┴───┬────┘
                                                                    │       │        │        │        │
                                                                    └───────┴────────┴────────┴────────┘
                                                                              Step 10 webhooks ⬜

PHASE 4 — PUSH          PHASE 5 — HANDSHAKE
┌────────┐              ┌────────┐
│ Step 11│              │ Step 12│
│ APNS/  │              │ JWT +  │
│  FCM   │              │blocklist│
│   ⬜   │              │   ⬜   │
└────────┘              └────────┘
```

**Counts:** 6 / 13 steps complete

---

## Two-server topology

```
              ┌──────────────────────────┐                    ┌──────────────────────────┐
   client ── ▶│  Server 1 (TypeScript)   │  RS256 JWT  ─────▶│   Server 2 (Python)       │
              │  identity & accounts      │  shared Redis      │   Vayumi orchestration    │
              │  /auth/login,/register…  │  blocklist (jti)   │   /ws/v1/session          │
              │  push tokens, sessions   │  (read-only S2)    │   voice + agents + tools  │
              │  OAuth, email sync       │                    │   email classify/notify   │
              └──────────────────────────┘                    └──────────────────────────┘
                       │                                                    │
                       └──────── Postgres + Redis (shared infrastructure)──┘
```

---

## Auth flow (Steps 1–3) ✅

```
Client                          Server 1                         Postgres / Redis
  │                                │                                    │
  │ POST /auth/register            │                                    │
  │───────────────────────────────▶│ insert user + identity             │
  │                                │───────────────────────────────────▶│
  │                                │ create session + refresh hash      │
  │◀───────────────────────────────│ sign RS256 access JWT (jti)        │
  │  access + refresh tokens       │                                    │
  │                                │                                    │
  │ POST /auth/token/refresh       │                                    │
  │───────────────────────────────▶│ rotate refresh, new access JWT     │
  │                                │                                    │
  │ POST /auth/logout              │                                    │
  │───────────────────────────────▶│ blocklist jti in Redis             │
  │                                │───────────────────────────────────▶│
```

---

## Email pipeline flow (Step 5 foundation ✅, Step 6+ extends)

```
Gmail/Outlook API          Server 1                         Server 2
      │                       │                                  │
      │  raw message          │                                  │
      │──────────────────────▶│ normalize → mask PII             │
      │                       │ POST /internal/emails/classify   │
      │                       │─────────────────────────────────▶│
      │                       │◀─────────────────────────────────│
      │                       │  category, keywords, summary     │
      │                       │                                  │
      │                       │ marketing/spam → DISCARD         │
      │                       │ else → unmask keywords           │
      │                       │ INSERT synced_emails (dedup)     │
      │                       │ POST /internal/emails/notify     │
      │                       │─────────────────────────────────▶│
      │                       │◀ handled: true|false             │
      │                       │ update agent_delivered / fallback│
```

**Step 6 adds:** OAuth connect → encrypted tokens in `oauth_integrations` → initial sync calls this pipeline.

---

## OAuth connect flow (Step 6 target)

```
Mobile/Web app              Server 1                    Redis              Gmail
      │                        │                         │                   │
      │ GET /gmail/connect     │                         │                   │
      │ (Bearer user JWT)      │                         │                   │
      │───────────────────────▶│ store state→userId      │                   │
      │                        │────────────────────────▶│                   │
      │◀───────────────────────│ redirect consent URL    │                   │
      │                        │─────────────────────────────────────────────▶│
      │                        │                         │                   │
      │ GET /gmail/callback    │                         │                   │
      │ ?code&state            │                         │                   │
      │───────────────────────▶│ lookup+delete state     │                   │
      │                        │────────────────────────▶│                   │
      │                        │ exchange code, encrypt tokens                 │
      │                        │ upsert oauth_integrations                     │
      │                        │ initial sync → processIncomingEmail()         │
      │◀───────────────────────│ redirect / JSON         │                   │
```

---

## Module status (sync with PLAN.md folder tree)

| Module | Status | Notes |
|---|---|---|
| `core/*` | ✅ | Config, db, redis, middleware, utils |
| `modules/auth` | ✅ | Full Phase 1 |
| `modules/sessions` | ✅ | |
| `modules/users` | ✅ | Phase 2 |
| `modules/settings` | ✅ | Phase 2 |
| `modules/notifications` | ⚠️ | Push token CRUD only; APNS/FCM in Step 11 |
| `modules/integrations/shared` | ✅ | Pipeline + Server 2 client |
| `modules/integrations/gmail` | ⚠️ | Connect stub 501 → Step 6 |
| `modules/integrations/outlook` | ⚠️ | Connect stub 501 → Step 7 |
| `modules/emails` | ⬜ | Step 8 |
| `cron/jobs` | ⚠️ | `cleanExpiredTokens` only → Step 9 |

---

## Verification commands

```bash
cd Server1
npm run typecheck
npm run build
npm run dev   # PORT from .env, default 3001
```

After Step 6 adds tests:

```bash
# TBD in step-06.md acceptance section
```
