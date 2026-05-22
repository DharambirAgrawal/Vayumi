# Step 04 — Web client v1

**Status:** ✅ done  
**Depends on:** step-03  
**Estimated effort:** 1 day  
**Owner:** you  
**Diagram pages:** 01, 04, 05, 17

---

## Goal

Polish the reference web client into a full voice conversation UI on top of the Step 3 voice loop: speak → hear reply → interrupt → speak again, with typed chat alongside voice, proper status/captions UI, and `client_state` / `client_control` handshake.

---

## Files this step creates or changes

```
web-client/
├── index.html                   CHANGED — conversation UI layout
├── client.js                    CHANGED — client_state/client_control, mic UX
└── style.css                    NEW — extracted styles
server/transport/
├── protocol.py                  CHANGED — client_state, mode, client_control, event
├── ws.py                        CHANGED — handle client_state/mode; interrupt → client_control
└── client_control.py            NEW — send_client_control / handle_client_state
tests/unit/
├── test_protocol.py             CHANGED — new message types
└── test_client_control.py       NEW
```

---

## Detailed tasks

### 1. Protocol (`server/transport/protocol.py`)

- Add client → server: `client_state`, `mode`
- Add server → client: `client_control`, `event`
- Extend discriminated unions and helpers

### 2. Client control (`server/transport/client_control.py`)

- `ClientControlSession` stores last reported `client_state` and session `mode`
- `send_client_control(websocket, command, reason, turn_id=None)` — serializes and sends
- `handle_client_state(payload)` — updates session snapshot, structlog
- On interrupt: send `stop` + `clear_queue` before cancelling TTS/Main
- On voice TTS `audio_start`: send `play` (reason `tts_start`) so client can sync

### 3. WebSocket (`server/transport/ws.py`)

- Attach `ClientControlSession` to `_WsSession`
- Handle `ClientStateMessage` and `ModeMessage` (no echo; log + store)
- Wire interrupt path through `send_client_control`

### 4. Web client

- Extract CSS to `web-client/style.css`
- **index.html:** connect bar, mode toggle (conversation / meeting stub), captions, chat thread, activity feed, toggle mic, interrupt
- **client.js** (PLAN §7.11 names):
  - `connect` / `sendJson` / `sendPcmFrame`
  - `startMic` / `stopMic` — AudioWorklet 16 kHz mono PCM (toggle mic)
- `hello` includes `capabilities.tts: true` (web client has a speaker; server defaults typed chat to voice per Rule 11)
- `reportClientState` / `handleClientState` — send `client_state` on **every** playback, capture, and visibility change (not only on connect)
- `handleServerAudio` / `handleClientControl` — honor `stop_capture` and `start_capture` (pause/resume mic during TTS echo suppression; Step 6 wires server-side enforcement)
- `renderCaption` (sentence-level, TTS-synced) and `renderChatMessage` (full response once per turn — distinct from captions; Step 6 adds server `chat_message` event)
- `renderEvent` / `renderTaskBoard`
  - `sendChat`, `sendMode`
- **Not in this step:** `uploadFile` (step 16)

### 5. Tests

- Protocol round-trips for new types
- `test_client_control.py` for session state + control serialization

---

## Acceptance test

Run in order. All must pass unless marked optional.

1. `python -m pytest tests/unit -q` — green with venv active.
2. `ruff check server/ tests/` — all checks passed.
3. `python -m uvicorn server.app:app --port 8080` boots cleanly (same env as step 3: Postgres, Redis, Groq, Kokoro, llama-server).
4. Open `http://localhost:8080` — polished UI loads (`style.css` linked).
5. Connect with token `dev` → `welcome`; server logs initial `client_state` after client hello.
6. **Voice:** Toggle mic, speak, stop mic → streamed `caption` partials + final; `audio_start` / binary TTS / `audio_end`; `client_state` reflects `recording` then `playing` then `idle`.
7. **Interrupt:** During TTS, click Interrupt → server sends `client_control` `stop`/`clear_queue` → playback stops → `client_state` confirms → mic works again.
8. **Typed chat:** At Step 4 completion, captions only (no TTS). Step 6 backfill adds `voice_and_chat` for typed input when `capabilities.tts=true`.
9. **Mode:** Toggle meeting stub → `mode` message logged; UI shows meeting label (no meeting logic).
10. `ping` → `pong`. Invalid token → close `4401`.
11. Step 3 behaviors preserved (voice loop, interrupt, chat captions).

If all pass, mark Step 4 ✅ in tracking files and stub `doc/step-05.md` if missing.

---

## Out of scope

- Memory, tools, sub-agents
- File/image upload (`uploadFile`)
- Mobile/ESP32 clients
- Real meeting mode (stub UI only)

---

## Risks and how we'll catch them

- Client/server playback state drift → `client_state` round-trip after every `client_control`.

---

## Notes for the next step

Step 5 adds memory v1 (warm profile, session history, versioned facts).
