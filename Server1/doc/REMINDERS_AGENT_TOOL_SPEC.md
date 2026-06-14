# Reminders Agent Tool Spec (Server 2 → Server 1)

This document is the contract for building **AI agent tools** on Server 2 that manage user reminders via Server 1. Use it when implementing tool definitions, handlers, and prompts.

**Related:** [`PLAN.md`](../PLAN.md) v1.9 Phase 3B · [`doc/step-06.md`](step-06.md) · Mobile app UI plan: [`doc/MOBILE_REMINDERS_UI_SPEC.md`](MOBILE_REMINDERS_UI_SPEC.md)

---

## Overview

| Concern | Owner |
|---|---|
| Reminder CRUD, scheduling, firing | **Server 1** |
| AI decides *when* and *what* to remind | **Server 2** (your agent tools) |
| Push to device (FCM) | Server 1 |
| Agent reacts when reminder fires | Server 2 (`POST /internal/agent/event`) |

Server 2 **does not** store reminders. It calls Server 1 APIs using a **service JWT** and passes `user_id` in the body.

---

## Authentication for agent tools

### Service JWT (Server 2 → Server 1)

Server 1 signs internal tokens with the same RS256 private key:

```
Authorization: Bearer <service_jwt>
```

JWT payload:

```json
{
  "scope": "internal",
  "iss": "server1"
}
```

- No expiry
- No `sub` / session — **you must send `user_id` in the request body** on create
- Server 1 sets `source: "agent"` on reminders created this way

**How Server 2 gets the token:** Either sign with the shared `JWT_PRIVATE_KEY`, or call a small helper that mirrors Server 1’s `signInternalServiceJwt()`.

### User JWT (mobile / web only)

End-user apps use normal access tokens. They do **not** send `user_id` in the body; Server 1 uses `req.auth.user.id` and sets `source: "user"`.

---

## Base URL

```
{SERVER1_URL}/api/v1/reminders
```

Example: `https://api.yourdomain.com/api/v1/reminders`

---

## Agent tool mapping (recommended)

Map these to Server 2 tool names (examples):

| Tool name (suggested) | HTTP | When the agent should use it |
|---|---|---|
| `create_reminder` | `POST /` | User asks to be reminded, or agent decides a follow-up is needed |
| `list_reminders` | `GET /` | Agent needs context on existing reminders |
| `get_reminder` | `GET /:id` | Agent needs one reminder’s details |
| `update_reminder` | `PATCH /:id` | Change time, title, recurrence |
| `cancel_reminder` | `POST /:id/cancel` | User says “cancel that reminder” |
| `delete_reminder` | `DELETE /:id` | Permanently remove (prefer cancel for soft stop) |

**Not for agent tools (user-only):** `POST /:id/snooze`, `GET /upcoming` (client offline sync).

---

## Tool: `create_reminder`

**Endpoint:** `POST /api/v1/reminders`  
**Auth:** Service JWT

### Request body

```json
{
  "user_id": "550e8400-e29b-41d4-a716-446655440000",
  "title": "Do homework",
  "body": "Review chapter 5 before class",
  "remind_at": "2026-06-08T14:00:00.000Z",
  "timezone": "America/New_York",
  "recurrence": null,
  "rrule": null,
  "max_fire_count": null
}
```

| Field | Required | Type | Notes |
|---|---|---|---|
| `user_id` | **Yes** (service JWT) | UUID | Target user |
| `title` | Yes | string (1–255) | Short label |
| `body` | No | string (≤5000) | Extra detail for agent / push |
| `remind_at` | Yes | ISO 8601 **with offset** | Stored in UTC; e.g. `2026-06-08T14:00:00.000Z` |
| `timezone` | Yes | IANA string | e.g. `America/New_York` — for display & recurrence |
| `recurrence` | No | `daily` \| `weekly` \| `monthly` \| `custom` \| null | One-time if null |
| `rrule` | No | string | Required when `recurrence` is `custom` (RFC 5545) |
| `max_fire_count` | No | positive int \| null | Cap recurring fires; null = unlimited |

### Recurrence examples

**One-time (most common for agent):**
```json
{
  "user_id": "...",
  "title": "Call mom",
  "remind_at": "2026-06-08T20:00:00.000Z",
  "timezone": "America/Chicago"
}
```

**Daily:**
```json
{
  "recurrence": "daily",
  "max_fire_count": 30
}
```

**Custom (e.g. weekdays) — use RRULE:**
```json
{
  "recurrence": "custom",
  "rrule": "FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR"
}
```

### Response `201 Created`

```json
{
  "reminder": {
    "id": "uuid",
    "user_id": "uuid",
    "title": "Do homework",
    "body": "Review chapter 5 before class",
    "remind_at": "2026-06-08T14:00:00.000Z",
    "timezone": "America/New_York",
    "recurrence": null,
    "rrule": null,
    "next_fire_at": "2026-06-08T14:00:00.000Z",
    "status": "pending",
    "source": "agent",
    "snooze_until": null,
    "fired_at": null,
    "fire_count": 0,
    "max_fire_count": null,
    "agent_delivered": false,
    "push_delivered": false,
    "created_at": "...",
    "updated_at": "..."
  }
}
```

### Agent prompt hints

- Always convert user’s local time to UTC for `remind_at`; always send their `timezone`.
- Prefer clear `title`; put context in `body` for when the agent speaks on fire.
- If user says “every day”, use `recurrence: "daily"`.

---

## Tool: `list_reminders`

**Endpoint:** `GET /api/v1/reminders`  
**Auth:** Service JWT *(today: user JWT only on list — see note below)*

> **Note:** List/get/upcoming currently require a **user JWT**. For agent listing, either:
> 1. Add a Server 2 internal route on Server 1 later (`GET /internal/reminders?user_id=`), or
> 2. Have Server 2 proxy with the user’s session (not ideal), or
> 3. **Recommended for v1:** Agent only **creates/updates/cancels**; listing is done via conversation memory + returned `id` from create.

If you add internal list support later, mirror the query params below.

### Query params (user JWT today)

| Param | Type | Description |
|---|---|---|
| `status` | `pending` \| `fired` \| `snoozed` \| `cancelled` | Filter |
| `source` | `user` \| `agent` | Filter |
| `from` | ISO datetime | `next_fire_at` after |
| `to` | ISO datetime | `next_fire_at` before |
| `limit` | 1–100 (default 20) | Page size |
| `cursor` | UUID | Pagination cursor |

### Response `200 OK`

```json
{
  "reminders": [ { "...ReminderDto" } ],
  "next_cursor": "uuid-or-null"
}
```

---

## Tool: `update_reminder`

**Endpoint:** `PATCH /api/v1/reminders/:id`  
**Auth:** Service JWT

### Request body (at least one field)

```json
{
  "title": "Do homework — chapter 6",
  "remind_at": "2026-06-09T14:00:00.000Z",
  "timezone": "America/New_York",
  "recurrence": "daily",
  "status": "pending"
}
```

| Field | Notes |
|---|---|
| `status` | Only `pending` or `cancelled` via PATCH |

Recomputes `next_fire_at` when `remind_at`, `recurrence`, or `rrule` change.

---

## Tool: `cancel_reminder`

**Endpoint:** `POST /api/v1/reminders/:id/cancel`  
**Auth:** Service JWT

**Body:** empty

Sets `status: "cancelled"`. Server 1 also notifies Server 2:

```json
{
  "type": "reminder.cancelled",
  "userId": "...",
  "payload": { "reminderId": "...", "title": "...", "source": "agent" }
}
```

---

## Tool: `delete_reminder`

**Endpoint:** `DELETE /api/v1/reminders/:id`  
**Auth:** Service JWT

Hard-deletes the row. Prefer **cancel** unless the user explicitly wants removal from history.

---

## What happens when a reminder fires (Server 2 inbound)

Server 1 does **not** call your agent tools. It calls **one inbound webhook**:

```
POST {SERVER2_INTERNAL_URL}/internal/agent/event
Authorization: Bearer <service_jwt>
```

### `reminder.fired` payload

```json
{
  "type": "reminder.fired",
  "userId": "550e8400-e29b-41d4-a716-446655440000",
  "payload": {
    "reminderId": "uuid",
    "title": "Do homework",
    "body": "Review chapter 5",
    "firedAt": "2026-06-08T14:00:00.000Z",
    "source": "agent"
  }
}
```

**Your handler should:**

1. Load user session / voice context if active.
2. Speak or message: e.g. “Reminder: Do homework — Review chapter 5.”
3. Return `{ "handled": true }` if the agent consumed the event; `{ "handled": false }` if not (push already went to device).

---

## Environment variables (Server 1)

These are **not** used by Server 2 agent tools directly, but explain how firing works:

| Variable | Purpose |
|---|---|
| `INTERNAL_REMINDER_SECRET` | Shared secret for **Supabase pg_cron → Server 1** only. Header: `X-Internal-Secret`. Prevents random callers from triggering `/internal/reminders/fire`. **Not** used by agent CRUD tools. |
| `REMINDER_FIRE_BATCH_SIZE` | Max reminders processed per cron tick (default `100`). Protects Server 1 from huge bursts. |
| `REMINDER_AGENT_EVENT_TIMEOUT_MS` | Timeout (ms) for Server 1 calling **your** `/internal/agent/event` (default `2000`). Retries: 3 attempts, backoff 1s / 2s. |

### Scheduling flow

```
Supabase pg_cron (every minute)
  → POST /internal/reminders/fire  (X-Internal-Secret)
  → Server 1 queries due reminders
  → FCM push to user devices
  → POST /internal/agent/event to Server 2
```

**Fallback:** Server 1 also runs `node-cron` every minute if pg_cron is not configured.

---

## Error responses

| HTTP | Code | Meaning |
|---|---|---|
| 401 | — | Missing/invalid JWT or internal secret |
| 422 | `VALIDATION_ERROR` | Bad body/query (Zod) |
| 404 | — | Reminder not found |
| 403 | — | User JWT required but service token used (on user-only routes) |

Validation errors include flattened Zod details in the response body.

---

## Example: Python tool handler (Server 2)

```python
import httpx
import jwt
import time

SERVER1_URL = "https://api.yourdomain.com"
JWT_PRIVATE_KEY = open("server1_private.pem").read()

def sign_service_jwt() -> str:
    return jwt.encode(
        {"scope": "internal", "iss": "server1"},
        JWT_PRIVATE_KEY,
        algorithm="RS256",
    )

def create_reminder(user_id: str, title: str, remind_at_iso: str, timezone: str, body: str | None = None):
    response = httpx.post(
        f"{SERVER1_URL}/api/v1/reminders",
        headers={"Authorization": f"Bearer {sign_service_jwt()}"},
        json={
            "user_id": user_id,
            "title": title,
            "body": body,
            "remind_at": remind_at_iso,
            "timezone": timezone,
        },
        timeout=10.0,
    )
    response.raise_for_status()
    return response.json()["reminder"]
```

---

## Checklist before going live

- [ ] Server 1 migration `0004_phase3b_reminders.sql` applied on Supabase
- [ ] `INTERNAL_REMINDER_SECRET` set in Server 1 `.env`
- [ ] Supabase pg_cron job configured (see `doc/step-06.md`)
- [ ] `SERVER2_INTERNAL_URL` set on Server 1
- [ ] Server 2 implements `POST /internal/agent/event`
- [ ] FCM service account path valid (for push on fire)
- [ ] Agent tools: create, update, cancel (+ delete if needed)

---

## Status fields reference

| `status` | Meaning |
|---|---|
| `pending` | Waiting for `next_fire_at` |
| `snoozed` | User snoozed; fires at new `next_fire_at` |
| `fired` | One-time reminder completed |
| `cancelled` | Stopped; will not fire again |

| `source` | Meaning |
|---|---|
| `user` | Created from app/web |
| `agent` | Created by Server 2 service JWT |
