# Step 03 — Voice plane: Groq STT + Kokoro TTS + interrupt

**Status:** ✅ done  
**Depends on:** step-02  
**Estimated effort:** 2 days  
**Owner:** you  
**Diagram pages:** 04, 10

---

## Goal

Add the first voice loop on top of the Step 2 engine path: client PCM audio becomes text through STT, Main Agent text becomes streamed speech through TTS, and interrupts can stop user-facing speech without stopping background work.

After this step the user can speak into the mic, get a spoken reply from Vayumi, interrupt mid-speech, and still see live captions while the assistant speaks.

---

## Files this step creates or changes

```
server/
├── voice/
│   ├── __init__.py              NEW
│   ├── types.py                 NEW
│   ├── boot.py                  NEW
│   ├── turn.py                  NEW
│   ├── stt/
│   │   ├── __init__.py          NEW
│   │   ├── base.py              NEW  — STTBackend protocol
│   │   └── groq.py              NEW  — Groq Whisper implementation
│   ├── tts/
│   │   ├── __init__.py          NEW
│   │   └── kokoro.py            NEW  — Kokoro streaming TTS
│   ├── vad/
│   │   ├── __init__.py          NEW
│   │   └── silero.py            NEW  — Silero VAD
│   └── interrupt.py             NEW  — interrupt controller + FSM
server/transport/
├── ws.py                        CHANGED — route audio_start/chunks/audio_end + interrupt
└── protocol.py                  CHANGED — interrupt + server audio_start/audio_end
server/app.py                    CHANGED — voice plane boot + shutdown
server/config.py                 CHANGED — voice settings
pyproject.toml                   CHANGED — groq, pykokoro, silero-vad, soundfile
.env.example                     CHANGED — voice env vars
web-client/
├── index.html                   CHANGED — interrupt button
└── client.js                    CHANGED — playback queue + interrupt button
tests/unit/
├── test_voice_*.py              NEW
└── test_protocol.py             CHANGED
```

---

## Detailed tasks

### 1. Configuration boundary

- Add `STT_BACKEND`, `GROQ_API_KEY`, `KOKORO_MODEL_DIR`, `KOKORO_VOICE` to `Settings` with code defaults.
- Document optional overrides in `.env.example`.
- Fail fast at boot when `STT_BACKEND=groq` and `GROQ_API_KEY` is missing.
- Fail fast at boot when `KOKORO_MODEL_DIR` does not exist.

### 2. Dependencies

Add from PLAN.md Section 11: `groq`, `pykokoro`, `silero-vad`, `soundfile`.

### 3. Voice modules

- `STTBackend.transcribe_stream()` in `server/voice/stt/base.py`.
- `GroqWhisper` buffers utterance PCM, wraps WAV, calls Groq Whisper, yields a final transcript event.
- `KokoroTTS.synthesize_stream()` sentence-splits text, synthesizes per sentence, resamples 24 kHz → 16 kHz, emits 20 ms PCM frames.
- `SileroVAD.accept_frame()` for server-side VAD surface/tests.
- `InterruptController` with speech FSM (`IDLE → THINKING → SPEAKING`, plus `QUEUED` for typed-chat backlog — full table in PLAN.md §7.5). `handle_interrupt`, `cancel_tts`, `cancel_main_decode`, `drop_partial_utterance`.
- **v1.7 deliverables (verified in Step 6 backfill):** `compute_respond_via(session_state, input_kind)` and `begin_tts_with_echo_suppression(turn_id)` — the only path to `audio_start`; always sends `stop_capture` before PCM and `start_capture` after `SELF_ECHO_SUPPRESSION_DELAY_MS` (1200 ms default, 300 ms when `capabilities.aec=true`).

### 4. Voice turn pipeline

- On `audio_end`, run STT → Main engine (P0 slot 0) → stream `caption` partials.
- Stream Kokoro TTS per completed sentence; send server `audio_start` / binary PCM / `audio_end`.
- `interrupt` cancels the active turn task and Main decode; does not cancel background work (none yet).

### 5. Transport + client

- Buffer binary PCM only while `audio_start` capture is active (no more unconditional echo).
- Typed `chat` remains captions-only (no TTS).
- Web client plays server TTS via an AudioContext queue; Interrupt button sends `interrupt {source:"button"}`.

### 6. Tests

Unit tests for protocol extensions, interrupt FSM, Groq STT (mocked), Kokoro helpers, Silero VAD, and voice boot validation.

---

## Acceptance test

Run these in order. All must pass unless marked optional.

1. `python -m pytest tests/unit -q` — green with the venv active.
2. `ruff check server/ tests/` — all checks passed.
3. `python -m uvicorn server.app:app --port 8080` boots cleanly when:
   - Postgres and Redis are reachable from `.env`.
   - `GROQ_API_KEY` is set.
   - `KOKORO_MODEL_DIR` exists with Kokoro ONNX assets.
   - Engine binary/model paths are valid.
   Logs show Postgres, Redis, LanceDB, llama-server, engine pool, and voice plane ready.
4. Boot fails clearly when `GROQ_API_KEY` is missing (groq backend) or `KOKORO_MODEL_DIR` is invalid.
5. Open `http://localhost:8080`. Connect with token `dev`.
6. **Voice:** Record 1s → streamed `caption` partials + final; server `audio_start`, binary TTS frames, `audio_end`.
7. **Interrupt:** During TTS playback, click Interrupt → speech stops; connection stays open; can record again.
8. **Typed chat:** At Step 3 completion, captions only (no TTS). After Step 6 backfill, typed chat defaults to `voice_and_chat` when `capabilities.tts=true` (PLAN.md Rule 11).
9. `ping` still returns `pong`. Invalid token still closes with `4401`.

**Echo suppression (PLAN.md Rule 12 — verified in Step 6):** On any TTS output, server sends `client_control { command: "stop_capture" }` before `audio_start`, streams PCM, sends `audio_end`, then `client_control { command: "start_capture" }` after the suppression delay (~1.2 s default). Unit tests assert ordering; manual check: mic indicator pauses during TTS.

---

## Out of scope

- Local faster-whisper fallback
- Server-side wake-word echo trap
- Memory, tools, sub-agents, proactive notifier
- Meeting mode
- Mobile/ESP32 clients
- Full Step 4 client polish (`client_state` / `client_control`)

---

## Risks and how we'll catch them

- Groq credentials missing in dev → boot fails fast with a clear `GROQ_API_KEY` error.
- Kokoro model files missing → boot fails fast on missing `KOKORO_MODEL_DIR`.
- Interrupts cancel Main/TTS only → `InterruptController` never touches engine slots beyond the active Main handle.

---

## Notes for the next step

Step 4 will polish the web client around the voice loop: AudioWorklet capture, playback controls, `client_state` / `client_control` handling, and conversation/meeting mode UI.
