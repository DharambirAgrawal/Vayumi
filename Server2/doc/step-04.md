# Step 04 — Web client v1

**Status:** ⬜ pending  
**Depends on:** step-03  
**Estimated effort:** 1 day  
**Owner:** you  
**Diagram pages:** 01, 04, 05

---

## Goal

Polish the reference web client into a full voice conversation UI on top of the Step 3 voice loop: speak → hear reply → interrupt → speak again, with typed chat alongside voice, proper status/captions UI, and `client_state` / `client_control` handshake.

---

## Files this step creates or changes

```
web-client/
├── index.html                   CHANGED — status, captions, activity feed, controls
└── client.js                    CHANGED — client_state/client_control, mic UX
server/transport/
├── protocol.py                  CHANGED — client_state client message (if not already)
├── ws.py                        CHANGED — handle client_state
└── client_control.py            NEW — send_client_control / handle_client_state
```

---

## Detailed tasks

_To be filled in before implementation begins._

---

## Acceptance test

_To be defined._

---

## Out of scope

- Memory, tools, sub-agents
- Mobile/ESP32 clients
- Meeting mode UI beyond stubs

---

## Risks and how we'll catch them

- Client/server playback state drift → `client_state` round-trip after every `client_control`.

---

## Notes for the next step

Step 5 adds memory v1 (warm profile, session history, versioned facts).
