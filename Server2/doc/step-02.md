# Step 02 — Engine plane: llama-server runner + slot pool + main-only completion

**Status:** ⬜ pending  
**Depends on:** step-01  
**Estimated effort:** 1–2 days  
**Owner:** you  
**Diagram pages:** 02, 06

---

## Goal

Boot the `llama-server` subprocess, expose a priority queue with 4 parallel slots, and replace the WebSocket echo handler so that a `Chat` message goes through the Main Agent (slot 0, P0) and the response streams back as `caption` events.

After this step the user can type a message in the web client and receive a streamed text reply from Gemma 3n E2B. No voice yet — text captions only.

---

## Files this step creates or changes

```
server/
├── engine/
│   ├── __init__.py              NEW
│   ├── runner.py                NEW  — llama-server subprocess lifecycle
│   ├── pool.py                  NEW  — priority queue + slot manager
│   └── prompt.py                NEW  — prompt template assembly
prompts/
│   └── main.txt                 NEW  — Main Agent system prompt
server/transport/
│   ├── ws.py                    CHANGED — chat → engine instead of echo
│   └── protocol.py              CHANGED — add Caption server message
web-client/
│   └── client.js                CHANGED — render streaming captions
```

---

## Detailed tasks

### 1. Configuration boundary

Keep `.env` small. Values that are secrets, machine-local paths, deployment ports, or operator overrides may be environment variables. Ordinary defaults belong in `server/config.py`.

For Step 2 this means:

- Add `LLAMA_SERVER_BIN`, `LLAMA_MODEL_PATH`, `LLAMA_PORT`, `LLAMA_PARALLEL_SLOTS`, and `LLAMA_CTX_PER_SLOT` to `Settings`.
- Provide sensible defaults in code:
  - `LLAMA_SERVER_BIN=./bin/llama-server`
  - `LLAMA_MODEL_PATH=./models/gemma-3n-E2B-it-Q4_K_M.gguf`
  - `LLAMA_PORT=8081`
  - `LLAMA_PARALLEL_SLOTS=4`
  - `LLAMA_CTX_PER_SLOT=8192`
- `.env.example` documents these as optional overrides, not required boilerplate.
- Fail fast at boot if the configured binary or model file is missing. Do not silently fall back to echo mode.

### 2. Dependencies

Add `httpx>=0.28` from `PLAN.md` Section 11. Do not add any dependency outside the frozen list.

### 3. `server/engine/runner.py`

Implement the `llama-server` subprocess lifecycle:

- `start_llama_server()` starts one process using the configured binary/model/port/slot count.
- `health_check()` calls the local `llama-server` health endpoint and returns a typed result.
- `stop_llama_server()` terminates the subprocess cleanly, then kills it if it does not exit.
- The start command must use:
  - `-m <model>`
  - `--port <LLAMA_PORT>`
  - `-np <LLAMA_PARALLEL_SLOTS>`
  - `--ctx-size <LLAMA_PARALLEL_SLOTS * LLAMA_CTX_PER_SLOT>`
  - `--slot-prompt-similarity 0.5`
- Log with structlog event names. Do not print.

### 4. `server/engine/pool.py`

Implement the engine queue shape from diagram page 06:

- Priorities: `P0` Main, `P1` sub-agents, `P2` summarizer.
- `submit(request, priority, slot_hint=None) -> CompletionHandle`
- `cancel(handle)`
- `reserve_slot(role, task_id)` and `release_slot(slot_id)` for future steps.
- Main calls use sticky slot 0 through `slot_hint=0`.
- Step 2 only needs P0 in runtime, but P1/P2 must exist as real queue priorities for the future shape.
- Stream tokens from `llama-server` to the caller as they arrive.

### 5. `server/engine/prompt.py` and `prompts/main.txt`

Create `build_main_prompt(context)` for a main-only prompt:

- Load `prompts/main.txt`.
- Include the user message.
- Do not include memory, tools, task board, directives, sub-agents, or voice instructions yet.
- Keep the prompt format simple and stable so Step 5 can add warm profile/history blocks without replacing the function.

### 6. App lifespan

In `server/app.py`:

- Start `llama-server` after Postgres, Redis, and LanceDB are healthy.
- Initialize one engine pool attached to `app.state.engine_pool`.
- Stop the pool and subprocess on shutdown before closing databases.
- If engine startup fails, the app refuses to start.

### 7. Transport behavior

In `server/transport/ws.py`:

- Keep auth, welcome, ping/pong, invalid message errors, and binary PCM echo behavior from Step 1.
- Replace only `Chat` echo:
  - Build a Main Agent prompt from the chat text.
  - Submit it to the engine pool with priority `P0` and `slot_hint=0`.
  - Stream response chunks as `caption` messages with `partial=true`.
  - Send a final `caption` with `partial=false` after completion.
- Do not add Supervisor, directives, memory, tools, STT, TTS, or interrupt behavior in this step.

### 8. Protocol and client

- Add server message type `caption` with payload `{ text: str, partial: bool }`.
- Update `serialize_server_message`.
- Update `web-client/client.js` so caption messages are rendered distinctly while preserving the existing JSON log.

### 9. Tests

Add unit tests for:

- `CaptionMessage` serialization.
- `build_main_prompt`.
- Runner command construction and health behavior using mocked process/HTTP edges.
- Engine pool streaming using a fake completion client.
- Existing protocol tests must keep passing.

---

## Acceptance test

Run these in order. All must pass unless explicitly marked optional.

1. `python -m pytest tests/unit -q` — green with the venv active.
2. `python -m uvicorn server.app:app --port 8080` boots cleanly when:
   - Postgres and Redis are reachable from `.env`.
   - `LLAMA_SERVER_BIN` points to a real `llama-server` binary.
   - `LLAMA_MODEL_PATH` points to the Gemma GGUF.
   Logs show Postgres, Redis, LanceDB, `llama-server`, and engine pool ready.
3. If `LLAMA_SERVER_BIN` or `LLAMA_MODEL_PATH` is missing, boot fails clearly. It must not silently return to echo mode.
4. Open `http://localhost:8080` in Chrome. The web client loads.
5. Connect with token `dev`. The log shows `welcome`.
6. Send a typed chat message. The log shows streamed `caption` messages, including a final one with `partial=false`.
7. Send `ping`. The server still replies with `pong`.
8. Click `Record 1s`. Binary PCM is still echoed back, preserving the Step 1 audio transport proof.
9. Connect with an obviously invalid token. The connection closes with code `4401`.

If all required items pass, mark Step 2 ✅ in `PLAN.md` Section 8, update `doc/roadmap.md`, `doc/history.md`, and `doc/tracker.md`, and create `doc/step-03.md` as a pending stub if it does not exist.

---

## Out of scope

- Voice (STT/TTS), interrupt, VAD
- Memory, tools, sub-agents
- Mobile/ESP32 client

---

## Notes for the next step

Step 3 will add Groq STT + Kokoro TTS + interrupt controller on top of the engine.
