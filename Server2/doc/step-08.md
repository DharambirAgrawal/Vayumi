# Step 08 — Sub-agent worker + signal bus

**Status:** ✅ complete  
**Depends on:** step-07 ✅ (tool plane complete)  
**Estimated effort:** 2–3 days  
**Owner:** you  
**Diagram pages:** 07, 15, 16

---

## Goal

Add **background sub-agents** for heavy work: `SubAgentWorker`, `report()` schema, signal bus, task board, and Supervisor spawn/resume/cancel — **without** the proactive notifier (Step 10).

This is the **rich** version of the same UX pattern Step 7 started:

| Phase | Step 7 (simple — done) | Step 8 (rich — this step) |
|-------|------------------------|---------------------------|
| Announce | `tool_started` + status caption | `task_step` pills (Path A); optional Main line on spawn |
| Work | `ToolRunner` (sync, ~seconds) | `SubAgentWorker` asyncio task (minutes, many tools) |
| Result | `[TOOL_RESULT]` → Main pass 2 → speak | `report(DONE)` → task_board → Main or Step 10 |
| User waits? | Yes for final answer (~1–2s) | **No** for the long job — work runs in background |

Sub-agents bind to the **Supervisor** (`user_id`), not the WebSocket. Device handover (PLAN.md §5.0) reattaches transport; workers keep running. `welcome{task_board_snapshot}` must list in-flight tasks after reconnect.

---

## Prerequisites (already built — do not redo)

From Steps 6–7:

- `ToolRegistry` + `ToolRunner` — sub-agents call tools **only** through `ToolRunner.execute(task_id, …)`.
- `[DELEGATE capability=main …]` → `server/orchestrator/tool_dispatch.py` (cheap tools, follow-up completion).
- `[DELEGATE capability=research|productivity|comms|data …]` today returns `not_capable` — **Step 8 replaces that branch with `spawn_subagent`.**
- `event{kind:tool_started|tool_done}` + activity feed rendering in `web-client/client.js`.
- `compute_respond_via`, echo suppression, `chat_message` vs `caption` (Step 6).

**Reuse `ToolRunner` without changes.** Sub-agent workers are new callers of the same runner.

---

## UX rules (PLAN.md §7.7 — locked for this step)

1. **Sub-agents never speak to the user.** No TTS, no WebSocket text from workers.
2. **Path A (default):** `report(STEP)` → `task_board` → `event{kind:task_step}` → activity feed only. Main stays quiet unless asked.
3. **Path B:** User asks status → Main reads `TaskBoard.render_for_main()` and answers in voice/chat.
4. **Path C (not this step):** Proactive spoken digests → Step 10 notifier.
5. **Spawn is non-blocking:** After `spawn_subagent`, the user turn can end; worker continues on P1 engine slot.
6. **Cheap tools stay on Main:** `capability=main` still goes through `tool_dispatch`, not `SubAgentWorker`.

**Latency note:** PersonaPlex-style “announce while working, then speak” for **quick** tools remains the Step 7 path. Step 8 optimizes **long** jobs (parallel work, feed progress). Spoken short ack before spawn (e.g. “I’ll research that”) is optional polish on Main’s spawn turn — not required for Step 8 acceptance.

---

## Files this step creates or changes

```
server/subagents/
├── __init__.py                  NEW
├── worker.py                    NEW — SubAgentWorker.run / resume / pause
└── report.py                    NEW — report() schema + validation
server/orchestrator/
├── signal_bus.py                NEW — publish / drain; PG audit
├── task_board.py                NEW — upsert_from_signal, render_for_main
├── tool_dispatch.py             CHANGED — capability≠main → spawn_subagent (not not_capable)
├── directives.py                CHANGED — ANSWER_TO, STOP_TASK parsing + strip
└── supervisor.py                CHANGED — spawn_subagent, apply_answer_to_task, cancel_task
server/engine/pool.py            CHANGED — P1 slot allocation + release on DONE/ERROR/cancel
server/db/schema.sql             CHANGED — tasks, signals tables
server/transport/
├── session_registry.py          CHANGED — task_board_snapshot in welcome (real data)
└── protocol.py                  CHANGED — ensure task_step|task_done|task_error documented
web-client/client.js             CHANGED — distinct pills for task_* vs tool_* events
prompts/main.txt                 CHANGED — when to DELEGATE research vs call main tools
tests/unit/
├── test_subagent_worker.py      NEW
├── test_signal_bus.py           NEW
├── test_task_board.py           NEW
├── test_directives_subagent.py  NEW — ANSWER_TO, STOP_TASK
└── test_supervisor_subagent.py  NEW — spawn, STEP without Main TTS, cancel
```

---

## Detailed tasks

### 1. `report()` + `SubAgentWorker`

- Pydantic `ReportSignal`: `task_id`, `kind` ∈ `STEP|NEEDS_INFO|DONE|ERROR`, `summary`, `payload`.
- `SubAgentWorker`: one ephemeral conversation per `task_id`; P1 engine slot from pool.
- Prompt: stub `prompts/sub/research.txt` (full bundles in Step 9).
- Loop: model step → `ToolRunner` for capability tools → `report()` only output.
- `resume_with(answer)` after `[ANSWER_TO]`; `pause()` after `NEEDS_INFO`.
- No transport access inside worker.

### 2. Signal bus + task board

- `SignalBus.publish(signal)` → Postgres row + in-memory `TaskBoard` update.
- Fields: `task_id`, `capability`, `status`, `latest_step`, `result_summary`, `blocked_reason`, `waiting_for`.
- `TaskBoard.render_for_main()` — short structured block on every Main prompt.
- Emit `event{kind:task_step|task_done|task_error}` to client (reuse activity feed).

### 3. Supervisor + `tool_dispatch` split

| `DELEGATE capability=` | Handler |
|------------------------|---------|
| `main` | `tool_dispatch.run_delegate_directives` (Step 7 — unchanged behavior) |
| `research`, `productivity`, `comms`, `data` | `spawn_subagent(goal, payload)` → `task_id`, background worker |

- `spawn_subagent(capability, goal, payload) -> task_id` per PLAN.md §7.11.
- `[STOP_TASK task_id=…]` → cancel worker, free slot, `event{task_error or task_done}`.
- `[ANSWER_TO task_id=… answer=… mode=reply|amendment]` → `apply_answer_to_task`.
- On spawn: emit `tool_started` (or dedicated task event) so feed shows work began.
- Inject `TaskBoard.render_for_main()` into `build_main_prompt` context.

### 4. Engine pool

- Track `task_id → slot_id` for P1 sub-agents; slot 0 remains sticky Main.
- Release slot on DONE, ERROR, cancel, or worker crash.

### 5. Web client + handover

- Activity feed: visually distinct **task** pills vs **tool** pills.
- `welcome{task_board_snapshot}` populated from live `TaskBoard` on connect/resume.

### 6. respond_via (read-only)

- Do **not** implement proactive notifier (Step 10).
- When NEEDS_INFO fires, Main’s next user-visible turn uses `compute_respond_via` — default `voice_and_chat` when visible and not recording (Rule 13).
- Document in tests/stubs: `build_synthetic_turn` (Step 10) must call `compute_respond_via(session_state, 'proactive')` before `handle_turn`.

---

## Acceptance test

Run in order. All must pass unless marked optional.

1. `python -m pytest tests/unit -q` — green.
2. `ruff check server/ tests/` — all checks passed.
3. Unit: `[DELEGATE capability=main …]` still uses `ToolRunner` (Step 7 behavior preserved).
4. Unit: `[DELEGATE capability=research …]` spawns worker; returns `task_id`; does **not** block until DONE.
5. Unit: `report(STEP)` updates task_board + emits `task_step` — **no** Main TTS for STEP alone (Path A).
6. Unit: `report(NEEDS_INFO)` → task `paused`; `TaskBoard` shows waiting state.
7. Unit: `[ANSWER_TO …]` resumes worker with injected answer.
8. Unit: `[STOP_TASK …]` cancels worker; P1 slot freed.
9. Web client: activity feed shows `task_step` / `task_done` distinct from `tool_started` / `tool_done`.
10. Optional live: delegate a multi-step research goal; see STEP pills updating; ask “what’s the status?” and hear Main summarize the board.

---

## Out of scope

- Proactive notifier + `build_synthetic_turn` (Step 10).
- Full capability bundles + `summarize_url` / MCP tools (Steps 9, 17).
- Spoken parallel “Sure, searching…” polish on Main cheap tools (Step 7 UX enhancement — optional anytime).
- LanceDB retrieval upgrade, summarizer (Steps 11–12).
- Changing `compute_respond_via`, echo suppression, or session singleton (Step 6 — already done).

---

## Risks and how we'll catch them

- Ghost tasks after crash — persist `tasks.status`; reconcile on Supervisor boot.
- Slot leaks — assert slot freed in every DONE/ERROR/cancel test.
- Main context bloat — `render_for_main()` capped (~N tasks, one line each); no raw sub-agent transcripts.
- Cross-task bleed — worker prompt includes only its `task_id` + capability stub.

---

## Notes for the next step

- **Step 9:** Capability bundles (`research`, `productivity`, `comms`), real sub prompts, `web_search` / `memory_recall` on sub-agent tool cards.
- **Step 10:** Notifier drains signal bus when user is silent; synthetic turns with `compute_respond_via`.
