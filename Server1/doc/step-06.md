# Step 06 — Reminders & scheduled tasks (Phase 3B)

**Status:** ✅ done  
**Depends on:** step-05 (email pipeline foundation — complete)  
**Estimated effort:** 2–3 days  
**Owner:** you  
**Agent tool contract:** [`doc/REMINDERS_AGENT_TOOL_SPEC.md`](REMINDERS_AGENT_TOOL_SPEC.md)

---

## Goal

Add a production-ready reminders system so users and the Server 2 AI agent can create, update, delete, snooze, and cancel scheduled tasks. When a reminder is due, Server 1:

1. Fires FCM push notifications to the user's registered devices.
2. Notifies Server 2 via the generic `POST /internal/agent/event` contract (`type: reminder.fired`).
3. Supports client offline sync via `GET /api/v1/reminders/upcoming?days=2`.

Scheduling is driven primarily by **Supabase pg_cron** calling `POST /internal/reminders/fire` every minute, with a **node-cron fallback** inside Server 1.

---

## Files this step creates or changes

```
Server1/
├── package.json                              CHANGED — add rrule
├── .env.example                              CHANGED — INTERNAL_REMINDER_SECRET, REMINDER_* vars
├── src/core/
│   ├── config/
│   │   ├── index.ts                          CHANGED — reminder env vars
│   │   └── reminders.ts                      NEW
│   ├── db/schema/
│   │   ├── reminders.ts                      NEW
│   │   └── index.ts                          CHANGED — export reminders
│   ├── db/migrations/
│   │   └── 0004_phase3b_reminders.sql        NEW
│   ├── middleware/
│   │   ├── authenticateUserOrService.ts      NEW
│   │   └── verifyInternalReminderSecret.ts     NEW
│   ├── redis/keys.ts                         CHANGED — reminderFireLock + TTL
│   └── types/express.d.ts                    CHANGED — internalService flag
├── src/modules/
│   ├── reminders/
│   │   ├── reminders.router.ts               NEW
│   │   ├── reminders.controller.ts           NEW
│   │   ├── reminders.service.ts              NEW — CRUD + fireRemindersNow()
│   │   ├── reminders.validators.ts           NEW
│   │   ├── reminders.types.ts                NEW
│   │   ├── reminders.recurrence.ts           NEW — rrule helpers
│   │   ├── reminders.constants.ts            NEW
│   │   └── server2.agentClient.ts            NEW — generic agent event client
│   ├── notifications/
│   │   ├── fcm.provider.ts                   NEW — thin sendPush()
│   │   └── notifications.service.ts          CHANGED — sendPushToUser()
│   └── cron/
│       ├── cron.bootstrap.ts                 CHANGED — register fireReminders job
│       └── jobs/fireReminders.ts             NEW
├── src/routes/index.ts                       CHANGED — mount reminders + internal router
└── src/app.ts                                CHANGED — mount /internal
```

---

## Detailed tasks

### 1. Database

- Add `reminders` table with UTC `remind_at`, `next_fire_at`, recurrence fields, delivery flags.
- Migration `0004_phase3b_reminders.sql` with indexes on `next_fire_at`, `user_id`, `status`.

### 2. Reminders module

- Full CRUD API at `/api/v1/reminders`.
- `authenticateUserOrService` for routes callable by Server 2 agent (service JWT, `source=agent`).
- `GET /upcoming?days=2` returns only `status=pending` reminders for client local notification sync.
- Snooze and cancel endpoints.

### 3. Fire pipeline

- `fireRemindersNow()` in `reminders.service.ts`:
  - Redis lock (`reminder:fire:lock`, TTL 55s).
  - Query `next_fire_at <= now()` AND `status IN (pending, snoozed)` LIMIT batch size.
  - Per reminder: FCM push + Server 2 agent event + update recurrence/next fire.
  - `Promise.allSettled` — one failure never blocks others.

### 4. Internal endpoint

- `POST /internal/reminders/fire` — HMAC via `X-Internal-Secret` header.
- Called by Supabase pg_cron (primary) or node-cron fallback (every minute).

### 5. Server 2 agent event client

- `POST {SERVER2_INTERNAL_URL}/internal/agent/event`
- Payload: `{ type, userId, payload }`
- Retry: 2s timeout, 3 attempts, backoff 1s/2s.

### 6. FCM stub

- Thin `fcm.provider.ts` using `FCM_SERVICE_ACCOUNT_PATH`.
- Phase 4 (Step 12) expands with APNS and full dispatch polish.

---

## Supabase pg_cron setup (one-time, in Supabase SQL editor)

Enable extensions if not already enabled:

```sql
CREATE EXTENSION IF NOT EXISTS pg_cron;
CREATE EXTENSION IF NOT EXISTS pg_net;
```

Schedule the fire webhook (replace URL and secret):

```sql
SELECT cron.schedule(
  'check-due-reminders',
  '* * * * *',
  $$
    SELECT net.http_post(
      url := 'https://your-server1-domain.com/internal/reminders/fire',
      headers := jsonb_build_object(
        'Content-Type', 'application/json',
        'X-Internal-Secret', '<INTERNAL_REMINDER_SECRET>'
      ),
      body := '{}'::jsonb
    );
  $$
);
```

To unschedule later:

```sql
SELECT cron.unschedule('check-due-reminders');
```

**Note:** node-cron fallback runs automatically inside Server 1 even before pg_cron is configured. For production, configure pg_cron so firing does not depend on a single Node process.

---

## Acceptance test

1. `npm run typecheck` and `npm run build` pass.
2. Create reminder via `POST /api/v1/reminders` with user JWT — returns `201`, `status=pending`, `next_fire_at` computed.
3. Create reminder via service JWT with `user_id` in body — `source=agent`.
4. `GET /api/v1/reminders/upcoming?days=2` returns only pending reminders in window.
5. Set `remind_at` to 1 minute ago, call `POST /internal/reminders/fire` with valid secret — reminder fires, `push_delivered`/`agent_delivered` updated.
6. Recurring daily reminder: after fire, `status` returns to `pending` with new `next_fire_at`.
7. One-time reminder: after fire, `status=fired`.
8. Snooze moves `next_fire_at` forward; cancel sets `status=cancelled`.
9. Invalid `X-Internal-Secret` on fire endpoint returns `401`.

---

## Out of scope

- Gmail/Outlook OAuth (Step 7+).
- Emails search API.
- APNS provider (Step 12).
- Client-side Notifee local notification scheduling (mobile app work).
- Migrating email notify to generic agent event route (Server 2 concern).

---

## Notes for the next step

- Step 7 (Gmail OAuth) is unchanged in scope — reminders are independent.
- Server 2 must implement `POST /internal/agent/event` to handle `reminder.fired` events.
- Configure `INTERNAL_REMINDER_SECRET` in production and set up Supabase pg_cron.
