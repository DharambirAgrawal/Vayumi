# Step 02 — Auth module

**Status:** ✅ done  
**Depends on:** step-01  
**Estimated effort:** 2–3 days  
**Owner:** you

---

## Goal

Implement the full identity layer so clients can:

1. Register with email+password (disposable emails rejected via `mailchecker`).
2. Log in with email+password (unverified users get `403 EMAIL_NOT_VERIFIED`).
3. Sign in / register with Google (`POST /auth/google`).
4. Verify email, resend verification, reset/change password.
5. Receive RS256 access JWT (`sub`, `sid`, `jti`, `device_type`, `scopes`) + opaque refresh token.
6. Refresh tokens with rotation; reuse of stale refresh revokes entire session family.
7. Logout (blocklist `jti` in Redis) or logout all sessions.

---

## Files this step created or changed

```
Server1/src/
├── core/db/
│   ├── schema/
│   │   ├── users.ts                       NEW
│   │   ├── user-identities.ts             NEW
│   │   ├── sessions.ts                    NEW
│   │   ├── email-verifications.ts         NEW
│   │   ├── password-reset-tokens.ts       NEW
│   │   └── index.ts                       CHANGED — re-exports Phase 1 schemas
│   └── migrations/
│       └── 0001_phase1_auth_foundation.sql NEW
├── core/middleware/
│   └── authenticate.ts                    CHANGED — RS256 verify + Redis blocklist check
├── core/utils/
│   └── jwt.ts                               CHANGED — access token sign/verify, payload shape
├── routes/index.ts                          CHANGED — mount /auth router
└── modules/auth/
    ├── auth.router.ts                       NEW
    ├── auth.controller.ts                   NEW
    ├── auth.service.ts                      NEW
    ├── auth.validators.ts                   NEW
    ├── auth.types.ts                        NEW
    └── auth.helpers.ts                      NEW — Google token verify, SMTP send
```

---

## Implementation summary

### Database (migration `0001`)

Tables: `users`, `user_identities`, `sessions`, `push_tokens`, `email_verifications`, `password_reset_tokens` with indexes per PLAN.md.

### Auth routes (`/api/v1/auth`)

| Method | Route | Notes |
|---|---|---|
| POST | `/register` | Creates user + identity + session + default settings row |
| POST | `/login` | Rate limited; requires verified email |
| POST | `/google` | Find-or-create via `user_identities`; auto-verified |
| GET | `/verify-email` | Token from query; marks user verified |
| POST | `/verify-email/resend` | Authenticated resend |
| POST | `/verify-email/resend/request` | Unauthenticated resend by email |
| POST | `/token/refresh` | Rotates refresh; reuse detection revokes family |
| POST | `/logout` | Blocklists access `jti` in Redis |
| POST | `/logout/all` | Revokes all sessions for user |
| POST | `/password/forgot` | Sends reset email |
| POST | `/password/reset` | Token + new password |
| POST | `/password/change` | Authenticated password change |
| GET | `/me` | Returns current user from JWT |

### Token design

- **Access token:** RS256 JWT, 15 min TTL, payload includes `jti` for blocklist.
- **Refresh token:** opaque `<sessionId>.<secret>`, bcrypt-hashed in DB, metadata in Redis (`RedisKeys.refreshToken`).
- **Blocklist:** `RedisKeys.tokenBlocklist(jti)` with TTL matching access token expiry.
- **Rotation:** every refresh issues new pair; old refresh invalid → revoke all sessions for user.

### Security rules implemented

- Disposable email rejection → `422 DISPOSABLE_EMAIL`.
- Unverified login → `403 EMAIL_NOT_VERIFIED`.
- Verification/reset tokens: random opaque, SHA-256 hashed in DB, short TTL metadata in Redis.
- `GOOGLE_CLIENT_ID` supports comma-separated audiences.

---

## Acceptance test (passed)

1. **`npm run typecheck`** and **`npm run build`** — pass.
2. Register → receive tokens → `GET /auth/me` returns user.
3. Refresh token rotation works; reusing old refresh revokes session family.
4. Logout blocklists JWT; subsequent requests with same access token fail.
5. Google Sign-In creates or finds account.
6. Unverified user cannot login with email+password.

---

## Out of scope

- Session list/revoke API (Step 3 — sessions module).
- Push token registration (Step 3).
- Avatar, profile PATCH (Step 4).
- Gmail/Outlook OAuth (Step 5+).

---

## Notes for the next step

Step 3 exposes session management (`GET/DELETE /sessions`) and push token CRUD (`POST/DELETE /notifications/push-token`), plus the `cleanExpiredTokens` cron job.
