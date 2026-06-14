# Step 14 — Local STT fallback

**Status:** ⬜ pending  
**Depends on:** step-13  
**Estimated effort:** 1 day  
**Owner:** you  
**Diagram pages:** TBD

---

## Goal

_faster-whisper local STT backend; automatic fallback when Groq is unreachable; transparent STTBackend swap._

---

## Files this step creates or changes

```
server/voice/stt/local.py          CHANGED — faster-whisper implementation
server/config.py                   CHANGED — offline / fallback flags
```

---

## Acceptance test

1. `python -m pytest tests/unit -q` — green.
2. Unit: local STT backend produces transcript from PCM.
3. Unit: fallback activates when Groq errors.

---

## Out of scope

- Wake-word echo trap (Step 15).
- File upload pipeline (Step 16).

---

## Notes for the next step

Step 15 adds server-side TTS echo trap coordination with client AEC.
