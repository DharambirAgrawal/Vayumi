# Step 13 — Meeting mode

**Status:** ✅ complete  
**Depends on:** step-12  
**Estimated effort:** 2 days  
**Owner:** you  
**Diagram pages:** m1–m8

---

## Goal

_Meeting mode toggle (Main dormant, transcript accumulates); diarization-friendly chunked storage; post-meeting summary stored as a fact._

---

## Files this step creates or changes

```
server/orchestrator/meeting.py         NEW — meeting state, passive/addressed routing, mode hooks
server/voice/meeting_turn.py           NEW — STT + meeting delegate
server/memory/meeting_storage.py       NEW — LanceDB meeting_chunks I/O
server/memory/meeting_summarizer.py    NEW — background post-meeting LLM summary
prompts/meeting_summary.txt            NEW — JSON-only meeting summary prompt
server/db/lancedb.py                   CHANGED — meeting_chunks table
server/transport/ws.py                 CHANGED — mode + audio_end branch
server/transport/turn_coordinator.py   CHANGED — start_meeting_turn
server/transport/session_registry.py   CHANGED — meeting_state field
server/config.py                       CHANGED — meeting thresholds
server/engine/prompt.py                CHANGED — build_meeting_summary_chat_messages
server/orchestrator/directives.py      CHANGED — [RECALL meeting:id]
server/memory/retrieval.py             CHANGED — get_meeting_recall
server/tools/memory_recall.py          CHANGED — meeting_id param
web-client/client.js                   CHANGED — continuous capture + meeting UI
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
- Client openWakeWord ONNX (server-side addressed detection for Step 13).

---

## Notes for the next step

Step 14 adds faster-whisper local STT fallback when Groq is unreachable.
