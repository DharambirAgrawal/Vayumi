# Step 06 — v1.7 contract backfill (session singleton + respond_via + echo suppression)

**Status:** ✅ done  
**Depends on:** step-05  
**Estimated effort:** 2 days  
**Owner:** you  
**Diagram pages:** 03, 05, 10

---

## Goal

Backfill the v1.7 behavioral contracts into the existing Step 1–5 code:

- **Session singleton** (one active WebSocket per user, device handover).
- **Typed chat speaks by default** (respond_via decision table).
- **Echo suppression** via `client_control` on every TTS output.
- **`chat_message`** as the canonical full response text, distinct from sentence-level captions.

This step is a **behavioral alignment pass**. It updates transport, voice, orchestrator, and client behavior to match PLAN.md v1.7 before we add new features in later steps.

---

## Files this step creates or changes

```
server/transport/
├── ws.py                        CHANGED — session singleton + handover
├── protocol.py                  CHANGED — chat_message + hello/welcome fields
└── client_control.py            CHANGED — start_capture/stop_capture handling
server/voice/
├── streaming_tts.py             NEW — PLAN §5.5 interleaved LLM sentence → TTS PCM
├── sentence_buffer.py           NEW — sentence boundary extraction from token stream
├── delivery.py                  CHANGED — chat_message; batch TTS fallback
├── echo_suppression.py          CHANGED — echo suppression wrapper
├── tts_stream.py                CHANGED — shared sentence regex
└── turn.py                      CHANGED — streaming TTS on voice turns
server/transport/
├── turn_coordinator.py          NEW — queue/defer voice, profile-only directives
server/orchestrator/
└── supervisor.py                CHANGED — respond_via, chat_message, queue policy; align run_turn → handle_turn(TurnInput) per §7.11
server/voice/turn.py             CHANGED — TTS path goes through echo suppression
server/config.py                 CHANGED — echo suppression delay settings
web-client/
├── index.html                   CHANGED — chat_message rendering + status
└── client.js                    CHANGED — start/stop capture + chat_message + queue depth
tests/unit/
├── test_protocol.py             CHANGED — new message types and fields
├── test_client_control.py       CHANGED — start_capture/stop_capture
├── test_voice_interrupt.py       CHANGED — respond_via + suppression
├── test_supervisor.py           CHANGED — chat_message + queue policy
├── test_sentence_buffer.py      NEW — sentence boundary extraction
└── test_streaming_tts.py        NEW — interleaved LLM→TTS pipeline
```

---

## Detailed tasks

### 1. Protocol updates (PLAN.md §5)

- **Hello**: add `capabilities.tts` (bool) and keep existing flags.
- **Welcome**: add `resumed: bool` and optional `task_board_snapshot`.
- **Server message**: add `chat_message { text, turn_id, final }`.
- **Event kinds**: add `session_superseded` with `reason`.
- **Client control**: ensure `start_capture` and `stop_capture` are in the enum.

### 2. Session singleton (PLAN.md §5.0)

- Keep a single Supervisor per `user_id` (not per session_id).
- On a new connection for an existing user:
  - Send `event { kind: "session_superseded", reason: "new_device" }` on the old connection.
  - Close old WS with code `SESSION_SINGLETON_CLOSE_CODE` (4001).
  - Attach the new WebSocket to the existing Supervisor via `attach_transport()`.
  - Send `welcome { resumed: true, session_id, task_board_snapshot }` to the new client.
- Reconnect with same `session_id` should reattach and send `welcome { resumed: true }`.

### 3. respond_via decision table (PLAN.md §7.5 Rule 13)

- Implement `compute_respond_via(session_state, input_kind)`.
- Default for typed chat in a voice-capable session is `voice_and_chat`.
- Block to `chat_only` if session is not voice-capable or client conditions apply.
- Typed chat **never interrupts** ongoing speech; policy is queue/replace (see below).
- Main can override the computed value with `[RESPOND_VIA chat|voice|both]`.

### 4. Echo suppression for ALL TTS (PLAN.md Rule 12)

- Add `begin_tts_with_echo_suppression(turn_id)`:
  - Send `client_control { command: "stop_capture", reason: "tts_start" }`.
  - Emit `audio_start`, stream PCM, emit `audio_end`.
  - After `SELF_ECHO_SUPPRESSION_DELAY_MS` (or AEC delay), send `client_control { command: "start_capture", reason: "echo_clear" }`.
- Echo suppression must run for voice, typed chat, and proactive responses.

### 5. Text delivery contract (PLAN.md §5.5)

- **Streaming TTS:** as each LLM sentence completes, emit `caption{partial:false}` → `audio_start` (once) → PCM for that sentence → continue LLM; after last sentence → `audio_end` → `chat_message`.
- `caption` partial tokens stream during LLM; sentence captions align with TTS per clause.
- `chat_message` is the full response text sent once per turn, regardless of respond_via.
- Batch `begin_tts_with_echo_suppression()` remains fallback when `tts_streamed_during_llm=false`.
- On interrupt or TTS failure:
  - Send `audio_end { interrupted:true }` or `audio_end { error:true }`.
  - Send `chat_message { final:false }` with partial text.
  - Send `client_control { clear_queue }` and `start_capture` immediately.

### 6. Typed chat queue policy (PLAN.md §5.5)

- Queue depth is **1 pending** beyond the currently playing speech.
- If a third typed chat arrives while one is playing and one is queued, replace the queued one.
- Voice interrupts always clear the queue.

### 7. Web client updates

- Render `chat_message` as the canonical chat bubble; keep captions as live streaming UI.
- Respect `client_control stop_capture` / `start_capture` by pausing and resuming mic capture.
- Display session handover notice when `event.kind == session_superseded`.
- Send `capabilities.tts` in `hello` and keep `client_state` updates.

### 8. Streaming TTS (PLAN.md §5.5)

- On each complete LLM sentence during generation: caption (sentence) → synthesize → stream PCM.
- `audio_start` once on first sentence; `audio_end` after flush; then `chat_message`.
- Voice and typed-chat turns both use `StreamingTtsPipeline` when `respond_via` includes voice.

### 9. Tests

- Protocol round-trips include `chat_message`, `start_capture`, `stop_capture`, and welcome fields.
- Session singleton: second connection closes the first with `session_superseded` and code 4001.
- `compute_respond_via` follows the Rule 13 decision table.
- Echo suppression: `stop_capture` precedes audio and `start_capture` is scheduled after.
- `chat_message` always sent; partial on interrupt is `final:false`.
- `test_sentence_buffer` and `test_streaming_tts` cover boundary drain and pipeline ordering.

---

## Acceptance test

Run in order. All must pass unless marked optional.

1. `python -m pytest tests/unit -q` — green.
2. `ruff check server/ tests/` — all checks passed.
3. Web client loads and connects; `welcome { resumed:false }` on first connect.
4. **Typed chat** triggers voice when `capabilities.tts=true` (audio_start + TTS + chat_message).
5. **Echo suppression**: each TTS output sends `stop_capture` before `audio_start`, then `start_capture` after delay.
6. **Session singleton**: a second connect for the same user sends `session_superseded` to the old WS and closes it with code 4001; new client gets `welcome { resumed:true }`.
7. **chat_message** is always sent; on interrupt it is partial with `final:false`.
8. **Chat-only**: if `capabilities.tts=false`, typed chat emits captions + chat_message only (no audio).
9. **Streaming TTS latency:** on a multi-sentence reply, first `audio_start` + PCM arrives after the **first sentence** completes (not after the full LLM reply).

---

## Out of scope

- Tool plane and sub-agents (Step 07+).
- Proactive notifier and summarizer.
- File uploads and attachments.

---

## Risks and how we catch them

- Echo suppression breaks mic capture → unit tests plus manual mic toggle check.
- Session handover loses state → ensure `task_board_snapshot` is included on welcome.
- Chat-only clients receive audio → explicit `capabilities.tts` gating in `compute_respond_via`.

---

## Notes for the next step

Step 07 adds the tool plane (registry, runner, web_search).
