# Step 04 — Users + settings + avatar storage

**Status:** ✅ done  
**Depends on:** step-03  
**Estimated effort:** 1–2 days  
**Owner:** you

---

## Goal

Let authenticated users manage their profile and app preferences:

1. View and update profile (name, email visibility rules per spec).
2. Upload avatar to Supabase Storage; URL stored on `users.avatar_url`.
3. Soft-delete account (cascade per schema).
4. Read and PATCH notification, privacy, and appearance settings.

Registration (Step 2) creates a default `user_settings` row automatically.

---

## Files this step created or changed

```
Server1/src/
├── core/db/
│   ├── schema/settings.ts                   NEW — user_settings table
│   └── migrations/0002_phase2_user_settings.sql NEW
├── core/utils/storage.ts                    NEW — Supabase Storage upload/delete
├── routes/index.ts                          CHANGED — mount /users, /settings
├── modules/users/
│   ├── users.router.ts                      NEW
│   ├── users.controller.ts                  NEW
│   ├── users.service.ts                     NEW
│   ├── users.validators.ts                  NEW
│   └── users.types.ts                       NEW
└── modules/settings/
    ├── settings.router.ts                   NEW
    ├── settings.controller.ts               NEW
    ├── settings.service.ts                  NEW
    ├── settings.validators.ts               NEW
    └── settings.types.ts                    NEW
```

Also: `doc/PHASE2_USER_SETTINGS_SPEC.md`, `doc/MOBILE_APP_AUTH_SPEC.md` — reference specs for mobile client contract.

---

## Implementation summary

### Users (`/api/v1/users`)

| Method | Route | Behavior |
|---|---|---|
| GET | `/profile` | Returns user profile (no secrets) |
| PATCH | `/profile` | Update name and profile fields |
| POST | `/avatar` | Multer upload → Supabase Storage → update `avatar_url` |
| DELETE | `/account` | Soft delete user (`deleted_at`) |

### Settings (`/api/v1/settings`)

| Method | Route | Behavior |
|---|---|---|
| GET | `/` | Returns notifications, privacy, appearance JSON blobs |
| PATCH | `/notifications` | Partial update |
| PATCH | `/privacy` | Partial update |
| PATCH | `/appearance` | Partial update |

Redis cache: `RedisKeys.userSettings(userId)`, `RedisKeys.userProfile(userId)`.

### Storage

- Supabase Storage bucket (`SUPABASE_STORAGE_BUCKET`, default `avatars`).
- Env: `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `SUPABASE_STORAGE_PUBLIC_URL`.

---

## Acceptance test (passed)

1. **`npm run typecheck`** and **`npm run build`** — pass.
2. `GET /users/profile` returns authenticated user.
3. `PATCH /users/profile` updates name.
4. Avatar upload returns public URL; profile reflects new `avatar_url`.
5. `GET /settings` returns default JSON; PATCH updates persist.
6. New registration creates `user_settings` row (migration backfill for existing users included).

---

## Out of scope

- OAuth email integrations (Step 5+).
- Push notification dispatch (Step 11).
- Server 2 internal routes (Step 12).

---

## Notes for the next step

Step 5 adds Phase 3 DB schemas (`oauth_integrations`, `synced_emails`), the shared email pipeline, Server 2 classify/notify client, and the integrations list API — without real Gmail/Outlook OAuth yet.
