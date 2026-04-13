# Vayumi

Vayumi is a voice assistant platform with a single live voice websocket and a separate HTTP fallback for typed chat.

## Current Transport Model
- Web and hardware voice stay on websocket connections.
- Typed chat uses the websocket when it is connected.
- If the websocket is unavailable, typed chat falls back to `POST /chat`.
- The HTTP fallback returns text only and can optionally route to an active websocket session when a matching `session_id` exists.

## Authentication Model
- Users authenticate via `POST /auth/register` and `POST /auth/login`.
- API routes use bearer tokens (`Authorization: Bearer <token>`).
- Websocket voice routes require the same token (query param or bearer header).
- Sessions are user-bound so backend data can be scoped per user.

## Canonical Docs
- [System integration architecture](./SYSTEM_INTEGRATION.md)
- [Orchestration API and tools](./ORCHESTRATION_API.md)
- [Original phase plan](./Plan.md)

## Project Layout
- `client/` React + TypeScript app
- `server/` FastAPI backend

## Verified Behavior
- Websocket handshake works for `/ws/audio` and `/ws/hardware`.
- Hardware audio still produces VAD end and wake-required events.
- Server-side TTS uses Kokoro ONNX when the repo model files are present.
- Local wake-word gating runs in-process first so Groq STT is not used just to search for the wake word.
- Chat-only websocket responses return `spoken: false`.
- HTTP `/chat` fallback returns a local text response when no websocket is available.
- Link attachments are now summarized through the instruction-aware `read_url` path, with protected-page failures returned as structured errors.

## Runtime Data Layout
- Runtime memory storage now defaults to `data/memory/`.
- Main memory index: `data/memory/memory.db`.
- Binary memory artifacts: `data/memory/blobs/`.
- Memory types share one SQLite DB and are separated by the `type` field (not separate DB files).

## Useful Endpoints
- `POST /auth/register`
- `POST /auth/login`
- `GET /auth/me`
- `GET /health`
- `GET /session/{session_id}/status`
- `POST /chat`
- `POST /session/{session_id}/resume-policy`
- `POST /session/{session_id}/resume`
- `POST /session/{session_id}/speak`
- `WS /ws/audio`
- `WS /ws/hardware`

## Development
See [SYSTEM_INTEGRATION.md](./SYSTEM_INTEGRATION.md) and [ORCHESTRATION_API.md](./ORCHESTRATION_API.md) for integration and runtime contracts.

Optional for richer link extraction on JS-heavy pages:
- `scrapling`
- `playwright`
