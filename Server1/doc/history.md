# History

This log tracks updates pushed to GitHub for Server 1. Each entry should be small, factual, and tied to the plan when relevant.

## How to log

- One entry per push or merged PR (or per completed build step).
- Keep the title short and specific.
- Include verification steps or note N/A.
- Reference plan sections when the change aligns with them.

## Entry template

## YYYY-MM-DD - Short title

**Scope:** docs | infra | auth | users | settings | integrations | emails | notifications | cron | tests

**Why:** One sentence on the problem or goal.

**Key changes:**
- Change 1
- Change 2

**Files/areas:**
- Path or module area

**Plan/diagram references:**
- PLAN section(s)

**Tests/verification:**
- Command(s) run or N/A

**Follow-ups:**
- Next steps, if any

---

## 2026-06-07 - Phase 3B reminders module (Step 6)

**Scope:** reminders | notifications | cron | docs

**Why:** Enable AI agent and frontend to create scheduled reminders with server-side firing, FCM push, and Server 2 agent event notification.

**Key changes:**
- Added `reminders` table + migration `0004_phase3b_reminders.sql`
- Full `/api/v1/reminders` CRUD + snooze/cancel/upcoming endpoints
- Internal `POST /internal/reminders/fire` with HMAC verification
- `fireReminders` node-cron fallback; pg_cron setup documented in step-06.md
- Thin `fcm.provider.ts` + `server2.agentClient.ts` generic event bus
- PLAN v1.9; roadmap/tracker renumbered (Gmail → Step 7)

**Files/areas:**
- `src/modules/reminders/*`
- `src/modules/notifications/fcm.provider.ts`
- `src/core/middleware/authenticateUserOrService.ts`
- `doc/step-06.md`, `doc/step-07.md`, `PLAN.md`, `doc/roadmap.md`

**Plan/diagram references:**
- PLAN v1.9 Phase 3B, rules 31–37, Server 2 agent event contract

**Tests/verification:**
- `npm run typecheck` and `npm run build` pass

**Follow-ups:**
- Configure `INTERNAL_REMINDER_SECRET` and Supabase pg_cron in production
- Server 2 must implement `POST /internal/agent/event`
- Step 7: Gmail OAuth

---

## 2026-06-07 - Backfilled step files for Steps 1–5

**Scope:** docs

**Why:** Completed work before the doc system existed had no `step-NN.md` files; backfill so agents and humans can read what was built without guessing from code.

**Key changes:**
- Created `doc/step-01.md` through `doc/step-05.md` (retrospective, status ✅ done)
- Updated `doc/tracker.md` and `doc/roadmap.md` to link all five files
- Aligned history entries below with step file references

**Files/areas:**
- Server1/doc/step-01.md … step-05.md, tracker.md, roadmap.md

**Plan/diagram references:**
- PLAN.md Section 8 (Steps 1–5 marked ✅)

**Tests/verification:**
- N/A (documentation only)

**Follow-ups:**
- Implement Step 6 (Gmail OAuth + provider)

---

## 2026-06-07 - Step-by-step doc system created


**Scope:** docs

**Why:** Mirror Server 2's agent workflow — roadmap, tracker, history, agent prompt, and incremental step files — so Server 1 can be built one step at a time.

**Key changes:**
- Added `agent-prompt.md`, `doc/roadmap.md`, `doc/tracker.md`, `doc/history.md`
- Added PLAN.md Section 8 (phase plan) and Section 9 (how to read doc/)
- Created `doc/step-06.md` as the current pending step (Gmail OAuth)
- Later same day: backfilled `doc/step-01.md` … `doc/step-05.md` for completed work

**Files/areas:**
- Server1/PLAN.md, Server1/agent-prompt.md, Server1/doc/*

**Plan/diagram references:**
- PLAN.md Section 8, Section 9

**Tests/verification:**
- N/A (documentation only)

**Follow-ups:**
- Implement Step 6 (Gmail OAuth + provider)

---

## 2026-05-13 - Step 5 complete: email pipeline foundation

**Scope:** integrations | infra | db

**Why:** Lay shared email infrastructure before wiring Gmail/Outlook OAuth — schemas, pipeline, Server 2 client, sync lock.

**Step file:** [`doc/step-05.md`](step-05.md)

**Key changes:**
- Drizzle schemas: `oauth_integrations`, `synced_emails` + migration `0003_phase3_oauth_and_synced_emails.sql`
- Shared modules: `email.pipeline.ts`, `email.masker.ts`, `server2.emailClient.ts`, `tokenVault.ts`, `emailSyncLock.ts`
- `signInternalServiceJwt()` for Server 2 internal calls
- Redis `setIfNotExists` for sync lock NX+EX
- Integrations list API + Gmail/Outlook connect stubs (501)
- Config: `integrations.ts`, Phase 3 env vars in `.env.example`

**Files/areas:**
- `src/core/db/schema/oauth-integrations.ts`, `synced-emails.ts`
- `src/modules/integrations/shared/*`
- `src/modules/integrations/integrations.*`
- `src/core/utils/fetchRetry.ts`, `postgres.ts`, `jwt.ts`

**Plan/diagram references:**
- PLAN.md v1.8 changelog, Email Pipeline, Server 2 Contract, Phase 3 checklist

**Tests/verification:**
- `npm run typecheck` and `npm run build` pass

**Follow-ups:**
- Step 6: Gmail OAuth + provider

---

## Step 4 complete — User profile & settings

**Scope:** users | settings | storage

**Why:** Let users manage profile, avatar, and app preferences after auth foundation.

**Step file:** [`doc/step-04.md`](step-04.md)

**Key changes:**
- Users module: profile CRUD, avatar upload, account deletion
- Settings module: notifications, privacy, appearance
- Supabase Storage for avatars
- `user_settings` schema + migration `0002_phase2_user_settings.sql`

**Plan/diagram references:**
- PLAN.md Phase 2, API Routes (Users, Settings)

**Tests/verification:**
- `npm run typecheck` and `npm run build` pass

---

## Steps 1–3 complete — Auth foundation

**Scope:** auth | sessions | notifications | cron | infra

**Why:** Establish identity layer so Server 2 can verify JWTs and read blocklist; mobile clients can register push tokens.

**Step files:** [`doc/step-01.md`](step-01.md) · [`doc/step-02.md`](step-02.md) · [`doc/step-03.md`](step-03.md)

**Key changes:**
- Project scaffold: Express, Drizzle, Redis, middleware stack
- Auth: register, login, Google Sign-In, email verify, password reset/change, JWT + refresh rotation
- Sessions: list/revoke, device tracking
- Notifications: push token register/delete
- Cron: `cleanExpiredTokens`
- Migration `0001_phase1_auth_foundation.sql`

**Plan/diagram references:**
- PLAN.md Auth Rules, Session & Device Tracking, Phase 1 checklist

**Tests/verification:**
- `npm run typecheck` and `npm run build` pass

**Follow-ups:**
- Step 4 user profile (completed — see [`doc/step-04.md`](step-04.md))
