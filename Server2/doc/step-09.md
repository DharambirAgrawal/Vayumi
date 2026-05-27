# Step 09 — Capability bundles

**Status:** ✅ complete  
**Depends on:** step-08  
**Estimated effort:** 2 days  
**Owner:** you  
**Diagram pages:** 08

---

## Goal

_Add research, productivity, and comms capability bundles with per-capability prompts, tool gates, and `summarize_url` / `fetch_html` tools._

---

## Files this step creates or changes

```
server/subagents/capabilities/
├── research/manifest.py         NEW
├── productivity/manifest.py     NEW
└── comms/manifest.py            NEW
prompts/sub/
├── research.txt                 NEW
├── productivity.txt             NEW
└── comms.txt                    NEW
server/tools/summarize_url.py    NEW
server/tools/fetch_html.py       NEW
server/subagents/worker.py       CHANGED — load_capability, render_tool_cards
```

---

## Acceptance test

1. `python -m pytest tests/unit -q` — green.
2. Unit: sub-agent sees only tools for its capability.
3. Unit: `summarize_url` returns normalized article text (httpx mocked).

---

## Out of scope

- MCP adapter (Step 17).
- Proactive notifier (Step 10).

---

## Notes for the next step

Step 10 adds the notifier; synthetic turns use `compute_respond_via(..., 'proactive')` per PLAN.md Rule 13.
