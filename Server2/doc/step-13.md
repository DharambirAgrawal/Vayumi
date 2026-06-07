# Step 13 — Meeting mode

**Status:** ⬜ pending  
**Depends on:** step-12  
**Estimated effort:** 2 days  
**Owner:** you  
**Diagram pages:** TBD

---

## Goal

_Meeting mode toggle (Main dormant, transcript accumulates); diarization-friendly chunked storage; post-meeting summary stored as a fact._

---

## Files this step creates or changes

```
server/orchestrator/meeting.py     NEW — meeting mode state + transcript accumulation
server/transport/ws.py             CHANGED — mode handling
web-client/client.js               CHANGED — meeting mode UI (stub → full)
```

---

## Acceptance test

1. `python -m pytest tests/unit -q` — green.
2. Unit: meeting mode suppresses Main voice turns.
3. Unit: post-meeting summary stored as versioned fact.

---

## Out of scope

- Local STT fallback (Step 14).
- File upload pipeline (Step 16).

---

## Notes for the next step

Step 14 adds faster-whisper local STT fallback when Groq is unreachable.
