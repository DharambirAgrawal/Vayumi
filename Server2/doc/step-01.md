# Step 01 — Project scaffold + WebSocket echo

**Status:** ⬜ pending  
**Depends on:** nothing  
**Estimated effort:** 1 day  
**Owner:** you

---

## Goal

Stand up the smallest possible version of Server 2 that:

1. Boots a FastAPI app via `uvicorn`.
2. Connects to Postgres, Redis, and a local LanceDB folder on startup; refuses to start if any are unreachable.
3. Verifies a Server 1 JWT on the WebSocket handshake.
4. Accepts a WebSocket connection at `/ws/v1/session?token=<jwt>` and echoes whatever JSON or binary the client sends.
5. Serves a one-file web client at `/` that opens the WebSocket, sends a typed message, sends a 1-second mic recording as binary, and shows everything echoed back.

**There is no LLM, no STT, no TTS in this step.** This step is purely about proving that the spine — auth + transport + a working client — is real. Every later step plugs in here.

---

## Files this step creates or changes

```
Server2/
├── pyproject.toml                   NEW
├── .env.example                     NEW
├── .gitignore                       NEW
├── docker-compose.dev.yml           NEW   (postgres + redis only)
├── server/
│   ├── __init__.py                  NEW
│   ├── app.py                       NEW
│   ├── config.py                    NEW
│   ├── logger.py                    NEW
│   ├── auth.py                      NEW
│   ├── db/
│   │   ├── __init__.py              NEW
│   │   ├── postgres.py              NEW
│   │   ├── redis.py                 NEW
│   │   └── lancedb.py               NEW
│   └── transport/
│       ├── __init__.py              NEW
│       ├── ws.py                    NEW
│       └── protocol.py              NEW
├── web-client/
│   ├── index.html                   NEW
│   └── client.js                    NEW
└── tests/
    ├── __init__.py                  NEW
    ├── conftest.py                  NEW
    └── unit/
        └── test_protocol.py         NEW
```

---

## Detailed tasks

### 1. `pyproject.toml`

Use `uv` (or `pip-tools` if you prefer). Lock to Python 3.12. Pin the deps from `PLAN.md` Section 11 — but in this step you only need a subset:

```
fastapi, uvicorn[standard], pydantic, pydantic-settings, structlog,
asyncpg, redis, lancedb, python-jose[cryptography], numpy
```

Plus dev: `pytest`, `pytest-asyncio`, `ruff`, `mypy`.

### 2. `server/config.py`

A `Settings(BaseSettings)` class. Required fields (server refuses to start if missing):

```
APP_ENV, PORT, LOG_LEVEL,
JWT_PUBLIC_KEY, SERVER1_REDIS_URL,
DATABASE_URL, REDIS_URL, LANCEDB_DIR
```

Validation rules: `APP_ENV in {"dev","prod"}`, `JWT_PUBLIC_KEY` parses as a valid RSA PEM, all URLs parse.

### 3. `server/logger.py`

`structlog` configured for JSON output in prod, pretty in dev. Expose one helper: `get_logger(name)`.

### 4. `server/db/*`

- `postgres.py`: an `asyncpg` pool created in `startup()`, closed in `shutdown()`. Run the `schema.sql` migration block on boot (idempotent — `CREATE TABLE IF NOT EXISTS` only). For step 1 the only table is:

  ```sql
  CREATE TABLE IF NOT EXISTS server_health (
    id SMALLINT PRIMARY KEY DEFAULT 1,
    last_boot TIMESTAMPTZ NOT NULL,
    CHECK (id = 1)
  );
  ```

- `redis.py`: an asyncio Redis client (regular Redis URL). On boot, `PING` it; if it fails, raise.

- `lancedb.py`: open a `lancedb.connect(LANCEDB_DIR)` and create a placeholder table called `_ping` if missing, with one row `{ ok: 1 }`. This proves the directory is writable.

### 5. `server/auth.py`

One function: `verify_token(token: str) -> TokenPayload`.

- Decode the JWT with `python-jose`, algorithm `RS256`, key = `JWT_PUBLIC_KEY`.
- Validate `exp`, `iat`, required claims (`sub`, `sid`, `jti`).
- Connect to **Server 1's** Redis (`SERVER1_REDIS_URL`) and check key `blocklist:<jti>`. If exists, raise.
- Returns a typed `TokenPayload` (Pydantic model: `user_id`, `session_id`, `jti`, `device_type`, `scopes`, `exp`).

This must work today against a token that Server 1 issues. No "we'll figure out auth later."

### 6. `server/transport/protocol.py`

Pydantic models for every JSON envelope in `PLAN.md` Section 5. For step 1, implement only:

- Client → server: `Hello`, `Chat`, `AudioStart`, `AudioEnd`, `Ping`.
- Server → client: `Welcome`, `Echo` (a temporary type just for this step), `Pong`, `Error`.

Add a `parse_message(raw: str) -> ClientMessage` discriminated-union helper. Wrong shape = `ValidationError` → server emits an `Error` and closes.

### 7. `server/transport/ws.py`

The WebSocket endpoint at `/ws/v1/session`. Behavior in step 1:

- Read `token` from query string.
- `verify_token(token)` — on failure, close with code `4401`.
- Accept the connection.
- Send a `Welcome { session_id, server_version }`.
- Loop:
  - On JSON frame: parse → for `Chat`, send back `Echo { kind: "chat", payload: <same> }`. For `Ping`, send `Pong`.
  - On binary frame: send back the same bytes (proving binary path works).
  - On `WebSocketDisconnect`: log and break.

Use a single `asyncio.TaskGroup` for inbound/outbound so we have the right shape from day one.

### 8. `server/app.py`

```
app = FastAPI(lifespan=lifespan)
app.mount("/", StaticFiles(directory="web-client", html=True))     # serves the client
app.add_websocket_route("/ws/v1/session", ws_endpoint)
```

The `lifespan` function:

1. Initializes Postgres pool + runs migration.
2. Initializes Redis (own + Server 1).
3. Initializes LanceDB.
4. Writes `last_boot = now()` into `server_health`.
5. Yields.
6. On shutdown, closes all three.

If any init step raises, the app **must not start**.

### 9. `web-client/index.html` + `client.js`

A single page with:

- A token input field (paste a JWT from Server 1).
- A "Connect" button.
- A status indicator (connecting / connected / closed).
- A text input + "Send" button (sends `Chat`).
- A "Record 1s" button — uses `getUserMedia` with `{ echoCancellation: true, noiseSuppression: true, channelCount: 1, sampleRate: 16000 }`, records 1 second of PCM, sends `AudioStart` then the binary frames then `AudioEnd`.
- A scrolling log of every JSON message received.

Stick to vanilla JS and the native `WebSocket` and `MediaRecorder`/`AudioWorkletNode` APIs. No build step. No npm. **This file must work in Chrome and Safari.** It is the contract test for the protocol.

### 10. Tests

- `tests/unit/test_protocol.py`: round-trip every message type through `parse_message` and assert the discriminator picks the right model.
- `tests/conftest.py`: a `pytest-asyncio` event-loop fixture, plus a `fake_token()` helper that signs a JWT with a test private key (the matching public key gets injected into `Settings` via env override).

CI later will add an integration test that boots the app against test containers.

---

## Acceptance test

Run these in order. All must pass.

1. `uv run pytest tests/unit -q` — green.
2. `docker compose -f docker-compose.dev.yml up -d` — postgres + redis come up.
3. `uv run uvicorn server.app:app --port 8080` — boots cleanly. Logs show "postgres ok / redis ok / lancedb ok".
4. Open `http://localhost:8080` in Chrome. Web client loads.
5. Generate a Server 1 access token (use `Server1`'s `/auth/login`). Paste into the client and click Connect. Status shows "connected" and the log shows `{ "type": "welcome", ... }`.
6. Type "hello" and Send. The log shows an `Echo { kind: "chat", payload: { text: "hello" } }`.
7. Click "Record 1s". The log shows `audio_start`, then a `binary frame received: 32000 bytes` line on the client side after the server echoes, then `audio_end`.
8. Try connecting with an obviously invalid token — connection closes with code `4401`.

If all 8 pass, mark step 1 ✅ in `PLAN.md` Section 8 and open `doc/step-02.md`.

---

## Out of scope (explicitly NOT in this step)

- LLM. No `llama-server`, no model files yet.
- STT/TTS. Echo is binary, not transcribed or synthesized.
- VAD, wake word, interrupt logic.
- Memory. The Postgres table is just a health-check row.
- Tools, sub-agents, signal bus.
- Mobile/ESP32 client. Web only.
- Production hardening (rate limit, CORS lockdown, TLS).

If you find yourself wanting any of the above, write it down for the relevant later step file. **Do not pull it into step 1.** That's exactly the trap that broke previous attempts.

---

## Risks and how we'll catch them

| Risk | Mitigation |
|---|---|
| JWT verification works in Server 1 but not Server 2 due to key-format mismatch | The acceptance test uses a real Server 1 token, not a synthetic one. If that fails, fix the PEM parsing now, not later. |
| `MediaRecorder` produces opus-in-webm instead of PCM | We don't use `MediaRecorder`. We use `AudioWorkletNode` + `Float32Array → Int16` conversion + raw `WebSocket.send(buffer)`. The web client code shows exactly this. |
| Browser blocks mic on `http://` non-localhost | Acceptance test specifies `localhost`. Production needs HTTPS — that's step 19. |
| LanceDB corrupts on crash | LanceDB is append-only and versioned by design; restart re-opens cleanly. |
| Postgres asyncpg pool exhaustion under reconnects | Use `min_size=2, max_size=10`. Verify by reconnecting the client 50 times in a manual stress test before closing the step. |

---

## Notes for the next step

`step-02.md` will:

- Drop the `llama-server` binary into `bin/` (or a path from env).
- Build `server/engine/runner.py` (subprocess lifecycle) and `server/engine/pool.py` (slot-priority queue).
- Replace the `Echo` handler so a `Chat` message goes through Main-only completion and the response streams back as `caption` events (no audio yet).

Do **not** start step 2 until every box in this file's acceptance test is ticked.
