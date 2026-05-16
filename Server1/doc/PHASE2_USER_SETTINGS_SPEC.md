# Server 1 Phase 2 Integration Guide (Users + Settings)
**Status:** Phase 2 complete
**Last updated:** 2026-05-10

This document summarizes Phase 2 features that are already implemented on Server 1 so an external agent can integrate them into the app without re-implementing backend logic.

## Phase 1 status (already implemented)
Phase 1 auth + sessions + push tokens are complete. Refer to [MOBILE_APP_AUTH_SPEC.md](MOBILE_APP_AUTH_SPEC.md) for the full details. Key capabilities that already exist:
- Auth: register, login, Google Sign-In, refresh, logout, password reset, email verification.
- Sessions: list/revoke sessions.
- Notifications: register/remove push token.

## Base configuration
- **Base URL:** `{API_URL}/api/v1`
- **Auth header:** `Authorization: Bearer <access_token>`
- **Error shape:**
```json
{ "error": { "code": "SOME_CODE", "message": "Human readable message", "details": {} } }
```

## Phase 2 features
- User profile (read/update)
- Avatar upload to Supabase Storage
- Account soft delete
- User settings (read/update for notifications, privacy, appearance)

## Data models
### User profile
```json
{
  "id": "uuid",
  "email": "user@example.com",
  "name": "Jane Doe",
  "avatar_url": "https://...",
  "is_verified": true,
  "created_at": "2026-05-10T12:00:00.000Z",
  "updated_at": "2026-05-10T12:00:00.000Z"
}
```

### User settings
```json
{
  "notifications": { "push_enabled": true },
  "privacy": { "share_profile": false },
  "appearance": { "theme": "light", "language": "en" },
  "updated_at": "2026-05-10T12:00:00.000Z"
}
```

Notes:
- Settings are **merged** on patch (partial updates). Any keys are allowed.
- An update body must include **at least one field**.
- A `user_settings` row is created during registration; migration backfills existing users.

---

## API routes (Phase 2)

### 1) Get profile
- **GET** `/users/profile` (protected)
- **Response:**
```json
{ "user": { ...profile } }
```

### 2) Update profile
- **PATCH** `/users/profile` (protected)
- **Body:**
```json
{ "name": "Jane Doe", "avatar_url": "https://..." }
```
- **Response:**
```json
{ "user": { ...profile } }
```

### 3) Upload avatar
- **POST** `/users/avatar` (protected)
- **Content-Type:** `multipart/form-data`
- **Form field:** `avatar` (file)
- **Constraints:** max 5 MB; types: `image/jpeg`, `image/png`, `image/webp`
- **Response:**
```json
{ "avatar_url": "https://..." }
```

**Storage details:**
- Avatar files are uploaded to **Supabase Storage** in a **public** bucket named `avatars`.
- The server stores and returns the **public URL** only.
- If you later want the bucket **private**, the API must return signed URLs instead.

### 4) Delete account
- **DELETE** `/users/account` (protected)
- **Behavior:** soft delete user + revoke all sessions/tokens
- **Response:**
```json
{ "success": true }
```

---

## Settings endpoints

### 1) Get full settings
- **GET** `/settings` (protected)
- **Response:**
```json
{ "settings": { ...settings } }
```

### 2) Update notifications
- **PATCH** `/settings/notifications` (protected)
- **Body:** any JSON object with at least one key
- **Response:**
```json
{ "settings": { ...settings } }
```

### 3) Update privacy
- **PATCH** `/settings/privacy` (protected)
- **Body:** any JSON object with at least one key
- **Response:**
```json
{ "settings": { ...settings } }
```

### 4) Update appearance
- **PATCH** `/settings/appearance` (protected)
- **Body:** any JSON object with at least one key
- **Response:**
```json
{ "settings": { ...settings } }
```

---

## Migration note
Server 1 auto-runs SQL migrations on startup. If you need to apply manually, run the SQL from:
- `src/core/db/migrations/0002_phase2_user_settings.sql`

---

## What is NOT in Phase 2
- Integrations (Phase 3)
- Push dispatch providers (Phase 4)
- Server-to-server handshake (Phase 5)
