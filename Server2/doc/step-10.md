# Step 10 — Proactive notifier + synthetic turns

**Status:** ⬜ pending  
**Depends on:** step-09  
**Estimated effort:** 1–2 days  
**Owner:** you  
**Diagram pages:** 11

---

## Goal

_Background loop that surfaces sub-agent DONE/NEEDS_INFO/ERROR signals as user-visible turns through the same `handle_turn` pipeline Main already uses — with `respond_via` computed per Rule 13._

---

## Files this step creates or changes

```
server/orchestrator/
├── notifier.py                  NEW — maybe_surface_signal, build_synthetic_turn, run loop
└── supervisor.py                CHANGED — wire notifier on boot
server/app.py                    CHANGED — start notifier task in lifespan
server/transport/protocol.py     CHANGED — notification message type (if not present)
web-client/client.js             CHANGED — notification toasts
tests/unit/
└── test_notifier.py             NEW — respond_via gating + debounce
```

---

## Detailed tasks

### 1. Notifier loop

- Tick every ~3 s (configurable); drain signal bus for session.
- Gates: user silent, importance threshold, min-interval debounce, `client_state.visible`, meeting mode, `capture=recording`.

### 2. `build_synthetic_turn(signals)` — Rule 13

- Set `input.kind = 'proactive'`.
- **Before** assembling Main context, call `compute_respond_via(session_state, input_kind='proactive')` (PLAN.md §7.5 full table).
- NEEDS_INFO → default **`voice_and_chat`** when client visible and not recording (even if DONE would wait).
- `visible=false` → `chat_only` + push via Server 1 when available.
- `capture=recording` or meeting mode → `chat_only`.
- Pass computed `respond_via` into `handle_turn` / `stream_main_response(context, respond_via)`.
- TTS must use `begin_tts_with_echo_suppression` (Rule 12).

### 3. Client

- Render `notification` toasts; full reply still arrives as `caption` + `chat_message` (+ audio if `voice_and_chat`).

---

## Acceptance test

1. `python -m pytest tests/unit -q` — green.
2. Unit: DONE signal + idle user + visible client → `compute_respond_via(..., 'proactive')` → `voice_and_chat`.
3. Unit: NEEDS_INFO + visible + not recording → `voice_and_chat`.
4. Unit: same signal + `visible=false` → `chat_only`.
5. Unit: `capture=recording` → `chat_only` (no TTS mid-recording).
6. Optional live: sub-agent DONE while user silent → hear + read proactive summary.

---

## Out of scope

- Push notification delivery implementation on Server 1 (stub event only).
- Digest policy tuning (PLAN.md §7.7 Path C) beyond one synthetic turn per gate pass.

---

## Notes for the next step

Step 11 upgrades LanceDB retrieval. Echo suppression and session singleton are unchanged — notifier reuses Step 6 contracts.
