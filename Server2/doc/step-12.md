# Step 12 — Summarizer (P2) + automatic compression

**Status:** ✅ complete  
**Depends on:** step-11  
**Estimated effort:** 2 days  
**Owner:** you  
**Diagram pages:** 09

---

## Goal

_P2 summarizer worker using the engine pool; automatic session compression when history exceeds 20k tokens; fact extraction from completed task results — all background, zero user-facing latency._

---

## Files this step creates or changes

```
server/memory/summarizer.py         NEW — summarize_session, extract_facts_from_task, schedule_*
prompts/summarizer.txt              NEW — JSON-only summarizer prompt
server/engine/prompt.py             CHANGED — build_summarizer_chat_messages
server/memory/session.py            CHANGED — token estimate, prune turns, update summary
server/orchestrator/supervisor.py   CHANGED — fire-and-forget schedule after turn
server/orchestrator/signal_bus.py   CHANGED — fire-and-forget facts_to_persist on DONE
server/config.py                    CHANGED — summarizer thresholds + retry settings
```

---

## Acceptance test

1. `python -m pytest tests/unit -q` — green.
2. Unit: session compression runs when history exceeds token threshold.
3. Unit: `extract_facts_from_task` writes versioned facts from task DONE payloads.

---

## Out of scope

- Meeting mode (Step 13).
- File upload / attachment summarization (Step 16).

---

## Notes for the next step

Step 13 adds meeting mode with diarization-friendly transcript accumulation.
