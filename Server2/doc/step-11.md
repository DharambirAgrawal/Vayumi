# Step 11 — LanceDB retrieval + memory_recall upgrade

**Status:** ✅ complete  
**Depends on:** step-10  
**Estimated effort:** 1 day  
**Owner:** you  
**Diagram pages:** 09

---

## Goal

_Full semantic retrieval via LanceDB; upgrade `memory_recall` and add `[RECALL doc:<doc_id>]` directive support._

---

## Files this step creates or changes

```
server/memory/retrieval.py         CHANGED — full LanceDB top-k query
server/tools/memory_recall.py      CHANGED — semantic search path
server/orchestrator/directives.py  CHANGED — [RECALL doc:...] parsing
```

---

## Acceptance test

1. `python -m pytest tests/unit -q` — green.
2. Unit: retrieval returns ranked snippets with citations for a seeded fact index.
3. Unit: `[RECALL doc:<id>]` injects snippet into Main context.

---

## Out of scope

- Summarizer (Step 12).
- MCP adapter (Step 17).

---

## Notes for the next step

Step 12 adds the P2 summarizer and automatic session compression at 20k tokens.
