# Vayumi Server 2 — Full Codebase Review

> Generated: 2026-06-07 after Step 13 (Meeting Mode) completion.
> Four parallel reviewers covered: core server paths, memory/tools/prompts, tools/registry/docs, and transport/protocol/client.

**Overall verdict:** The architecture is coherent and correctly designed. All issues below are real, but none are structural — they range from runtime bugs to quality cleanups.

---

## Tier 1 — Bugs that will break at runtime

Fix these before using meeting mode in production.

### 1. `meeting_summarizer` uses the wrong engine pool API

**File:** `server/memory/meeting_summarizer.py:85–90`

`_call_meeting_summary_llm` calls `engine_pool.complete(...)` with `CompletionPriority.P2` and reads `result.text`. Neither exists:

- The engine pool only exposes `complete_chat()` (returns `ChatCompletionResult` with `.content`)
- The correct priority is `CompletionPriority.P2_SUMMARIZER`

`summarizer.py:101–106` does this correctly. No existing unit test exercises this path end-to-end (tests mock `summarize_meeting`). **Post-meeting summaries silently never run.**

**Fix:** Use `complete_chat()`, `.content`, and `P2_SUMMARIZER` — mirror `summarizer.py`.

---

### 2. `ws.py` ModeMessage handler uses `engine_pool` before it is bound

**File:** `server/transport/ws.py:273–281`

`engine_pool` is passed to `on_mode_change` but is only assigned inside the `ClientStateMessage` branch, not at the outer `_handle_text` scope. Any `ModeMessage` from the client (i.e. every time the mode dropdown is toggled) raises a `NameError` and crashes the message handler.

**Fix:** Resolve `engine_pool` from `websocket.app.state.engine_pool` inside the ModeMessage branch, or bind it at the top of the handler.

---

### 3. `drain_pending_voice` always routes to conversation mode

**File:** `server/transport/turn_coordinator.py:128`

`drain_pending_voice` calls `start_voice_turn` unconditionally. If audio is deferred while a meeting turn is running, when the deferral drains it is misrouted through the normal STT+Main conversation path instead of `start_meeting_turn`.

**Fix:** Check `session.client_control.mode == "meeting"` and branch to `start_meeting_turn` accordingly — same branch already in `_handle_audio_end`.

---

## Tier 2 — Correctness and security issues

Fix soon.

### 4. Meeting chunks not scoped by `user_id` on reads

**Files:** `server/memory/meeting_storage.py:64,97` · `server/memory/retrieval.py:142`

Both `list_meeting_chunks` and `search_meeting_chunks` filter only by `meeting_id`. The `get_meeting_recall` fallback in `retrieval.py` also passes no user filter. Since meeting IDs are human-readable timestamps (`YYYYMMDD-HHMMSS`), a user who knows another user's meeting ID could query their chunks.

**Fix:** Add `user_id` to the LanceDB `where` clause in both read functions.

---

### 5. Meeting ID collision

**File:** `server/orchestrator/meeting.py:61`

`_new_meeting_id()` uses `datetime.now().strftime("%Y%m%d-%H%M%S")`. Two meetings started within the same second share the same ID — colliding fact key and confusing LanceDB rows.

**Fix:** Append 4 random hex chars: `... + "-" + uuid.uuid4().hex[:4]`.

---

### 6. `_flush_buffer` records only the first speaker for multi-speaker chunks

**File:** `server/orchestrator/meeting.py:185`

`speaker = state.buffer[0].speaker` is used as the chunk's speaker field. A 30-second chunk often spans multiple speakers — the LanceDB row's `speaker` column becomes misleading.

**Fix:** Use `"MIXED"` when `len({u.speaker for u in state.buffer}) > 1`.

---

### 7. `EventPayload.kind` does not declare `meeting_started` / `meeting_ended`

**File:** `server/transport/protocol.py:229–237`

`EventPayload.kind` is a closed `Literal` enum. `meeting.py` emits `"meeting_started"` and `"meeting_ended"` outside that enum, and omits the required `task_id` field. Pydantic may coerce or silently accept this depending on model config, but it is a protocol contract violation.

**Fix:** Add `"meeting_started"` and `"meeting_ended"` to the `kind` Literal, and make `task_id` optional (defaulting to `""`).

---

### 8. `route: "none"` type mismatch

**Files:** `server/transport/protocol.py:74` · `server/voice/respond_via.py:48–49` · `server/transport/client_control.py:31`

Both the protocol and `compute_respond_via` reference `route == "none"` as a valid value, but `ClientControlSession.route` does not include `"none"` in its `Literal` type annotation. This is a silent type error that can mask routing bugs.

**Fix:** Add `"none"` to `ClientControlSession.route`'s type annotation.

---

## Tier 3 — Quality, duplication, and latency

Clean up when convenient.

### 9. Sync `embed_text` blocks the async event loop

**Files:** `server/memory/meeting_storage.py:40,94` · `server/memory/retrieval.py:85` · `server/memory/facts.py:108`

`embed_text` runs PyTorch sentence-transformer inference synchronously, blocking the event loop for 20–100ms per call. Meeting chunks and retrieval are already in background tasks so the impact is moderate, but `facts.set_fact` is called from the main turn path (for `[REMEMBER]` directives).

**Fix:** `await asyncio.get_event_loop().run_in_executor(None, embed_text, text)` at each call site.

---

### 10. `meeting_id` missing from `memory_recall` tool schema

**File:** `server/tools/__init__.py:149–161`

`memory_recall` is registered for the `main` capability with `key`, `chain`, `query`, `k` in the schema — but not `meeting_id`. The function itself accepts it (added in Step 13), but the LLM cannot pass it via native function calling. The `[RECALL meeting:...]` directive path works; native tool calling cannot reach meeting memory.

**Fix:** Add `"meeting_id": {"type": "string"}` to the `properties` dict in both `memory_recall` registrations (main and research).

---

### 11. Duplicated helpers across both summarizer modules

**Files:** `server/memory/summarizer.py` · `server/memory/meeting_summarizer.py`

The following are copied verbatim between the two files:
- `_JSON_FENCE_RE` + brace-extraction JSON parser
- `_summarizer_slot_hint`
- `_track_background_task`
- Per-job `asyncio.Lock` pattern

**Fix:** Extract to a shared `server/memory/_background.py` utility module.

---

### 12. `_escape_lancedb_str` defined in two places; `lancedb.py` version is weaker

**Files:** `server/memory/retrieval.py:34` · `server/memory/meeting_storage.py:23` · `server/db/lancedb.py:88–89`

`retrieval.py` and `meeting_storage.py` escape both `"` and `'`. `lancedb.py` only escapes `"`. All three should use the same helper from `server/db/lancedb.py`.

---

### 13. STT pipeline copy-pasted between `turn.py` and `meeting_turn.py`

**Files:** `server/voice/turn.py` · `server/voice/meeting_turn.py`

About 70% of `meeting_turn.py` is verbatim from `turn.py`: drop check, viability gate, `turn_id`, `chunk_iter`, STT loop, transcript filter, logging, and the `try/except CancelledError` block.

**Fix:** Extract to a shared `async def _run_stt(stt, pcm_chunks) -> str | None` helper in `server/voice/transcript.py` or a new `server/voice/stt_pipeline.py`.

---

### 14. `schedule_session_summarization` skipped on direct-answer turns

**File:** `server/orchestrator/supervisor.py:585`

Summarization is only scheduled at the end of the delegate/follow-up path. Turns that return a direct answer (no tools, no delegates) skip the scheduling call at line 585. Over time this causes sessions to grow unbounded until the 20k token threshold is only reachable via the delegate path.

**Fix:** Move `schedule_session_summarization(...)` to an unconditional `finally` block at the end of `run_turn`.

---

### 15. Stale comments and hardcoded strings in `tool_dispatch.py`

**File:** `server/orchestrator/tool_dispatch.py:99–103`

`_run_one_delegate` still says "sub-agents ship in a later step" — they shipped in Step 8. Also, `format_subagent_spawn_block` always outputs "Background research started" regardless of actual capability (e.g. for comms/email tasks).

---

### 16. `plan_acknowledgment` does not handle `[RECALL meeting:...]`

**File:** `server/orchestrator/directives.py:307–315`

`plan_acknowledgment` scans for early-return patterns but `RECALL_MEETING_RE` is not in its pattern list. A model output like `"Let me check that. [RECALL meeting:20260607]"` will not have the ack text truncated at the directive boundary.

**Fix:** Add `RECALL_MEETING_RE` to the patterns list in `plan_acknowledgment`.

---

## Tool extensibility — your question

Adding any new tool (calendar, SMS, email, etc.) is **fully supported** by the current architecture. No changes to supervisor, ws.py, or turn coordinator are needed. The pattern:

1. **Create** `server/tools/your_tool.py` — one `async def your_tool(*, user_id, ...) -> ToolResult` function
2. **Register** it with `registry.register(ToolEntry(...))` in `server/tools/__init__.py`
3. **For Main native calling:** add the name to `MAIN_OPENAI_TOOL_NAMES` in `openai_schema.py` and mention it in `prompts/main.txt`
4. **For sub-agent tools** (email, comms): register under the correct capability and add to that capability bundle's `allowed_tools` list

Email is already registered — `read_email` and `send_email` under the `comms` capability in `__init__.py`. The stubs in `server/tools/comms_email.py` just need real implementations and OAuth wiring from Server 1. No architectural changes needed.

---

## Fix priority table

| Priority | Issues |
|---|---|
| **Immediate** (runtime bugs) | #1 meeting_summarizer wrong API, #2 `engine_pool` NameError in ws.py, #3 `drain_pending_voice` meeting routing |
| **Soon** (correctness/security) | #4 user_id scoping on chunk reads, #5 meeting ID collision, #6 MIXED speaker label, #7 EventPayload kind enum, #8 route type |
| **Backlog** | #10 `meeting_id` in tool schema, #14 summarization on no-delegate turns, #16 `plan_acknowledgment` missing RECALL_MEETING_RE |
| **Cleanup** | #9 `run_in_executor` for embed_text, #11–13 dedup helpers, #15 stale comment |
