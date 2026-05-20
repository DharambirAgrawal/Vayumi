# Step 06 — Tool plane

**Status:** ⬜ pending  
**Depends on:** step-05  
**Estimated effort:** 2 days  
**Owner:** you  
**Diagram pages:** 08

---

## Goal

_Add tool registry, runner, tool_search, web_search, and Main direct tool calls._

---

## Files this step creates or changes

```
server/tools/
├── __init__.py                  NEW — registry bootstrap + tool registration
├── registry.py                  NEW — ToolEntry/ToolResult models + ToolRegistry
├── runner.py                    NEW — ToolRunner.execute + confirmation handling
├── tool_search.py               NEW — tool_search() discovery tool
├── web_search.py                NEW — Tavily primary + DDG fallback
├── memory_save.py               NEW — tool wrapper for facts.set
└── memory_recall.py             NEW — tool wrapper for facts.get/chain
server/orchestrator/
├── directives.py                CHANGED — parse/validate [DELEGATE ...] for main tools
└── supervisor.py                CHANGED — execute main tool calls + emit tool events
server/transport/protocol.py     CHANGED — event kinds: tool_started/tool_done
web-client/client.js             CHANGED — render tool events in activity feed
prompts/main.txt                 CHANGED — guidance for tool calls via [DELEGATE]
tests/unit/
├── test_tools_registry.py       NEW
├── test_tools_runner.py         NEW
├── test_tools_search.py         NEW
├── test_tools_web_search.py     NEW
├── test_directives_tools.py     NEW
└── test_supervisor_tools.py     NEW
```

---

## Detailed tasks

### 1. Tool models + registry

- Implement `ToolEntry`, `ToolResult`, and `ToolCard` (Pydantic models) per PLAN.md §7.10.
- Add `ToolRegistry` with `register()`, `get()`, `resolve_for_capability()`, and `search()`.
- Enforce unique tool names, JSON schema presence, and capability gating at registration.

### 2. Tool runner

- Implement `ToolRunner.execute(task_id, tool_call)`:
	- Validate tool exists and capability is allowed.
	- Validate args against `args_schema`.
	- Run with timeout (asyncio), return normalized `ToolResult`.
	- Emit `tool_started` and `tool_done` events with latency and tool name.
- Implement confirmation pipeline stubs (`confirmation_required` result shape + id/hash).

### 3. Core tools (main-only for this step)

- `tool_search(query, capability=None)` returns compact `ToolCard` list.
- `web_search(query, max_results=5)`:
	- Tavily primary when `TAVILY_API_KEY` is set.
	- DuckDuckGo HTML fallback when Tavily is unavailable or key missing.
	- Normalize results to `{title, url, snippet, source}` list.
- `memory_save` and `memory_recall` wrappers around `memory.facts` for tool usage.

### 4. DELEGATE for main tool calls

- Extend `directives.py` to parse `[DELEGATE capability=main goal="..." payload={...}]`.
- Define `payload` shape for main tool calls:
	- `{ "tool": "web_search"|"tool_search"|"memory_recall"|"memory_save", "args": { ... } }`.
- In `Supervisor`, when a main tool directive is encountered:
	- Run the tool via `ToolRunner`.
	- Inject a compact tool result block into a follow-up completion (same pattern as RECALL).
	- If capability is not `main`, return `ToolResult.status="not_capable"` and continue.

### 5. Prompt updates

- Update `prompts/main.txt` with explicit guidance:
	- Main can call only the cheap tools above.
	- Use `[DELEGATE capability=main ...]` with the payload schema.
	- Say one short intent line before calling a tool (per PLAN.md §7.10).

### 6. Protocol + client activity feed

- Add `tool_started` / `tool_done` to the `event.kind` enum in `protocol.py`.
- Render these tool events in the web client activity feed with a simple status label.

### 7. Tests

- Registry: uniqueness, capability resolve, search filtering.
- Runner: timeout behavior, confirmation_required shape, not_capable handling.
- Web search: Tavily success, DDG fallback, normalized output shape (httpx mocked).
- Directives: DELEGATE parsing + invalid capability behavior.
- Supervisor: main tool call executes, tool result injected, tool events emitted.

---

## Acceptance test

Run in order. All must pass unless marked optional.

1. `python -m pytest tests/unit -q` — green.
2. `ruff check server/ tests/` — all checks passed.
3. Unit: `ToolRegistry.resolve_for_capability("main")` returns only main tools.
4. Unit: `web_search` uses Tavily when key is set; falls back to DDG when not.
5. Unit: DELEGATE main tool call triggers `tool_started`/`tool_done` events.
6. Web client still loads and shows tool events in the activity feed.
7. Optional live: run server, ask "search for latest AI news"; see a short tool event and a response.

---

## Out of scope

- Sub-agents, signal bus, task board, notifier (Step 7+).
- MCP adapter and capability bundles (Steps 8 and 16).
- LanceDB retrieval and summarizer (Steps 10–11).
- File uploads / attachments (Step 15).

---

## Risks and how we'll catch them

- Tavily/ترنت fallback flakiness — mock httpx in unit tests; enforce timeouts.
- Prompt ambiguity for tool calls — explicit directive schema in `prompts/main.txt` and unit tests for DELEGATE parsing.
- Tool result injection loops — guard against recursive DELEGATE in the follow-up completion.

---

## Notes for the next step

- Step 7 adds sub-agent worker + signal bus; tool runner should be reusable without changes.
- Step 8 will expose `web_search`/`memory_recall` to sub-agent capabilities.
