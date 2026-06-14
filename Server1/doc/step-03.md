# Step 03 — Sessions + push tokens + cron

**Status:** ✅ done  
**Depends on:** step-02  
**Estimated effort:** 1 day  
**Owner:** you

---

## Goal

Complete Phase 1 client-facing session and device management:

1. List active sessions for the authenticated user.
2. Revoke a specific session by ID.
3. Register and delete push notification tokens (APNS/FCM token storage only — dispatch is Step 11).
4. Run `cleanExpiredTokens` cron to purge expired verification, reset, and session rows.

---

## Files this step created or changed

```
Server1/src/
├── routes/index.ts                          CHANGED — mount /sessions, /notifications
├── modules/sessions/
│   ├── sessions.router.ts                   NEW
│   ├── sessions.controller.ts               NEW
│   ├── sessions.service.ts                  NEW
│   └── sessions.types.ts                    NEW
├── modules/notifications/
│   ├── notifications.router.ts              NEW
│   ├── notifications.controller.ts          NEW
│   ├── notifications.service.ts             NEW — push token CRUD only
│   ├── notifications.validators.ts          NEW
│   └── notifications.types.ts               NEW
└── modules/cron/
    ├── cron.bootstrap.ts                    NEW — registers scheduled jobs
    ├── cron.types.ts                        NEW
    └── jobs/
        └── cleanExpiredTokens.ts            NEW
```

---

## Implementation summary

### Sessions (`/api/v1/sessions`)

| Method | Route | Auth | Behavior |
|---|---|---|---|
| GET | `/` | Yes | List user's active sessions (device type, name, last seen) |
| DELETE | `/:sessionId` | Yes | Revoke session; invalidate refresh token |

Session records created at login (Step 2) include: `device_type`, `device_name`, `device_fingerprint`, `refresh_token_hash`, `expires_at`.

Redis cache: `RedisKeys.userSessions(userId)` with `RedisTTL.userSessions`.

### Notifications (`/api/v1/notifications`)

| Method | Route | Auth | Behavior |
|---|---|---|---|
| POST | `/push-token` | Yes | Upsert push token for user (platform: ios/android) |
| DELETE | `/push-token` | Yes | Remove token on logout or uninstall |

Push tokens owned by `user_id`; `session_id` is informational only (PLAN.md design rule).

### Cron

- **`cleanExpiredTokens`** — removes expired `email_verifications`, `password_reset_tokens`, and inactive/expired `sessions`.
- Registered in `cron.bootstrap.ts` via `node-cron`.
- Phase 3 adds four more jobs in Step 9.

---

## Acceptance test (passed)

1. **`npm run typecheck`** and **`npm run build`** — pass.
2. After login, `GET /sessions` lists the current session.
3. `DELETE /sessions/:id` revokes session; refresh with that session's token fails.
4. `POST /notifications/push-token` stores token; `DELETE` removes it.
5. Cron job registered on boot (visible in logs).

---

## Out of scope

- APNS/FCM actual push dispatch (Step 11).
- User profile / settings (Step 4).
- Email sync (Step 5+).

---

## Notes for the next step

Step 4 adds `modules/users` and `modules/settings`, Supabase Storage for avatars, and migration `0002_phase2_user_settings.sql`.
