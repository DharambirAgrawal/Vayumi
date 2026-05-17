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

_To be filled in before implementation begins._

---

## Acceptance test

_To be defined._

---

## Out of scope

- Voice (STT/TTS), interrupt, VAD
- Memory, tools, sub-agents
- Mobile/ESP32 client

---

## Notes for the next step

Step 3 will add Groq STT + Kokoro TTS + interrupt controller on top of the engine.
