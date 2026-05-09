# Mobile App Authentication Integration Guide (Phase 1)

This document provides a comprehensive integration guide for the Mobile App to connect with the Vayumi Server 1 Authentication API.

## Base Configuration

- **Base URL:** `{API_URL}/api/v1`
- **Authentication Header:** All protected routes require an access token in the header:
  `Authorization: Bearer <access_token>`

---

## Token Lifecycle & Security

The system uses a two-token architecture to ensure users **do not need to log in repeatedly**:
1. **Access Token (15 min):** RS256 JWT used for all protected API requests. Keep this in volatile memory (RAM) or standard state (like Redux/Zustand/Context).
2. **Refresh Token (90 days):** Opaque string used to get a new token pair. **Must be stored securely**.
   - *React Native Tip:* Use `expo-secure-store` or `react-native-keychain` to save this token. Do **not** use `AsyncStorage` as it is not encrypted.

### Token Refresh Flow & Rotation
- **Silent Refresh:** When an API call returns `401 Unauthorized`, automatically call `/api/v1/auth/token/refresh` with your `refresh_token`.
- **Rotation:** Every time you refresh, the server will issue a *new* `refresh_token`. You must overwrite the old one in your secure storage.
- **Reuse Protection:** If an old or invalid `refresh_token` is used, the backend assumes the session is compromised and immediately revokes the **entire session family** (logging the user out of all devices).

---

## Shared Device Payload
Any endpoint that creates a session (Register, Login, Google Sign-In) expects a shared device payload in the request body to track active sessions properly.

**Device Object:**
```json
{
  "device_type": "mobile_ios", // or "mobile_android"
  "device_name": "iPhone 15 Pro", // Optional but highly recommended
  "device_fingerprint": "unique_hardware_id_or_hashed_identifier" // Optional
}
```

---

## 1. Authentication Endpoints

### 1.1. Email Registration
Registers a new user. The backend will automatically send a verification email.

- **Endpoint:** `POST /auth/register`
- **Auth Required:** No
- **Request Body:**
```json
{
  "email": "user@example.com",
  "password": "strongPassword123",
  "name": "John Doe", // Optional
  "device_type": "mobile_ios",
  "device_name": "iPhone 15 Pro"
}
```
- **Response (200 OK):**
```json
{
  "user": { ... },
  "tokens": {
    "access_token": "eyJhb...",
    "refresh_token": "..."
  },
  "verification_sent": true
}
```

### 1.2. Email Login
- **Endpoint:** `POST /auth/login`
- **Auth Required:** No
- **Request Body:**
```json
{
  "email": "user@example.com",
  "password": "strongPassword123",
  "device_type": "mobile_ios",
  "device_name": "iPhone 15 Pro"
}
```
- **Response (200 OK):** Returns `user` and `tokens`.

### 1.3. Google Sign-In
Use the native Google SDK on iOS/Android to obtain an `id_token`, then send it to the backend. The backend handles verifying the token and either creating an account or logging the user in.

- **Endpoint:** `POST /auth/google`
- **Auth Required:** No
- **Request Body:**
```json
{
  "id_token": "google_provided_jwt_id_token",
  "device_type": "mobile_android",
  "device_name": "Pixel 8"
}
```
- **Response (200 OK):** Returns `user` and `tokens`.

### 1.4. Refresh Token
Use this when the access token expires (401 response).

- **Endpoint:** `POST /auth/token/refresh`
- **Auth Required:** No
- **Request Body:**
```json
{
  "refresh_token": "your_current_refresh_token"
}
```
- **Response (200 OK):** Returns a completely new `tokens` object. Update Keychain immediately.

### 1.5. Logout (Current Device)
Revokes the current session and blocks the access token. 

- **Endpoint:** `POST /auth/logout`
- **Auth Required:** Yes (Bearer Token)
- **Response (200 OK):** `{ "success": true }`
- **Mobile Action:** Clear token from memory and `refresh_token` from Keychain. If you have a Push Token registered, make sure to call `DELETE /notifications/push-token` *before* logging out.

### 1.6. Logout All Devices
Revokes every active session the user has across all devices.

- **Endpoint:** `POST /auth/logout/all`
- **Auth Required:** Yes (Bearer Token)
- **Response (200 OK):** `{ "success": true }`

---

## 2. Password Management

### 2.1. Forgot Password
Sends a password reset link to the email.
- **Endpoint:** `POST /auth/password/forgot`
- **Auth Required:** No
- **Request Body:** `{ "email": "user@example.com" }`

### 2.2. Change Password (Logged In User)
Allows a logged-in user to update their password. Note: This will automatically log out all other sessions for security.
- **Endpoint:** `POST /auth/password/change`
- **Auth Required:** Yes (Bearer Token)
- **Request Body:**
```json
{
  "current_password": "oldPassword123",
  "new_password": "newStrongPassword456"
}
```

---

## 3. User & Session Retrieval

### 3.1. Get Current User ("Me")
Fetches the current user profile and linked identities (e.g., if they have Google linked).
- **Endpoint:** `GET /auth/me`
- **Auth Required:** Yes (Bearer Token)

### 3.2. List Active Sessions
Lists all active login sessions (e.g., to show the user "Where you're logged in").
- **Endpoint:** `GET /sessions`
- **Auth Required:** Yes (Bearer Token)

### 3.3. Revoke Specific Session
Logs out a specific session by its ID.
- **Endpoint:** `DELETE /sessions/:sessionId`
- **Auth Required:** Yes (Bearer Token)

---

## 4. Notifications / Push Tokens

Whenever the mobile app obtains a push token (FCM for Android or APNs for iOS), register it with the backend.

### 4.1. Register Push Token
- **Endpoint:** `POST /notifications/push-token`
- **Auth Required:** Yes (Bearer Token)
- **Request Body:**
```json
{
  "token": "device_apns_or_fcm_token_string",
  "platform": "ios" // or "android"
}
```

### 4.2. Remove Push Token
Always call this **before** executing a `POST /auth/logout` to stop receiving pushes for the logged-out user on this device.
- **Endpoint:** `DELETE /notifications/push-token`
- **Auth Required:** Yes (Bearer Token)
- **Request Body:**
```json
{
  "token": "device_apns_or_fcm_token_string"
}
```
