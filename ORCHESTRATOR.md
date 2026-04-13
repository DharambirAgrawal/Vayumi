# Orchestrator Architecture Plan

---

## 1. What This Is

The orchestrator is the supervisor layer between the Vayumi server and all LLM inference.
It owns every conversation, every tool call, every sub-agent session, every signal, and every
mode decision. Nothing talks to anything else directly — everything flows through here.

Position in the stack:

```
User (voice / typed chat)
        ↕
Vayumi Server  (transport, VAD, STT, TTS, wake word, interrupt control)
        ↕  AgentRunner.run() / AgentRunner.cancel()
Orchestrator Supervisor   ← this is what we are building
        ↕                           ↕
Main LLM Worker Process     Sub-agent Worker Process(es)
        ↕
MemoryOS
```

Vayumi is the transport and interruption control plane. The orchestrator is the intelligence
and state plane. They are cleanly separated. The Vayumi doc's Section 8 states this
explicitly: "Let orchestrator decide task-level continuation/flush behavior after interrupt."

---

## Implementation Policy (Current)

These are the active policy decisions for the current build cycle:

1. Main LLM remains low-context and personalized.
    It keeps only direct tools needed for fast single-step tasks and user interaction quality
    (memory ops, web search, and lightweight utility tools like current date/time).

2. Sub-agent access is in **full-tool testing mode** right now.
    For rapid testing and validation, spawned sub-agents can access all registered tools.
    This is controlled as a policy flag in orchestrator code and can be switched back to
    capability-scoped access without changing tool implementations.

3. Capability routing still exists and remains the long-term production path.
    Even with full-tool testing mode enabled, capability labels are preserved so we can switch
    to strict bundle routing later for lower hallucination risk.

4. Skills stay in separate files and are loaded dynamically at spawn time.
    The main model does not carry long skill text; skill references are injected only where
    needed to avoid context bloat.

5. Long conversation control is mandatory.
    History compression + asynchronous memory extraction remains required to operate within
    the 32k context budget.

---

## 2. How FunctionGemma Does Function Calling

FunctionGemma is schema-first. Tools are not passed as Python callables to LiteRT.

How it works:
1. Tool JSON schemas are injected as text inside the developer prompt.
2. When the model wants to call a function it outputs a structured tag:
   `<start_function_call>call:function_name{key:value}<end_function_call>`
3. The orchestrator parses this tag, executes the real Python function, and injects the
   result back as the next message.
4. The model continues — either calling another function or producing its final reply.

```python
# Correct usage — no tools= parameter
with engine.create_conversation(messages=messages) as conversation:
    response = conversation.send_message(user_input)
    output = extract_text(response)
    if "<start_function_call>" in output:
        call = parse_function_call(output)
        result = execute(call.function_name, call.params)
        response2 = conversation.send_message(
            f"[TOOL RESULT for {call.function_name}]: {result}"
        )
```

The **parse-execute-inject loop** is the core execution primitive. It runs inside every
worker process — both Main LLM and sub-agents.

```
while conversation is active:
    response = conversation.send_message(current_input)
    text = extract_text(response)

    if no function call tag in text:
        this is the final reply — return it

    call = parse_function_call(text)

    emit UX status event BEFORE executing (user sees it immediately)

    result = execute_function(call.function_name, call.params)

    current_input = "[TOOL RESULT for {name}]: {result}"
    loop continues
```

---

## 3. Tool Access — Exactly Who Gets What

### Main LLM Direct Tools

The Main LLM gets full JSON schemas for direct tools that are instant, single-step,
and safe to call mid-conversation without spawning a sub-agent.

| Tool | What it does |
|------|--------------|
| `current_time` | Return current UTC time (placeholder utility) |
| `current_date` | Return current UTC date (placeholder utility) |
| `web_search` | Search the web via Tavily |
| `memory_search` | Search long-term memory |
| `memory_save` | Save a fact or preference |
| `memory_update` | Correct a stored memory item |
| `memory_update_by_query` | Update memory using a search query |
| `memory_delete` | Delete a memory item |
| `memory_ingest` | Ingest structured content into memory |
| `memory_delete_links` | Remove link-based memory entries |
| `memory_get_user_model` | Fetch personalization profile |
| `memory_add_turn` | Add a turn to short-term memory |
| `memory_flush_session` | Flush short-term memory buffer |

These schemas are always present in the Main LLM's developer prompt.

### Capability Menu (always in Main LLM prompt, no schemas)

For everything else, the Main LLM does not see tool names or schemas. It sees a capability
menu — a small text block describing what kinds of work can be delegated. The orchestrator
maps capability names to tool IDs internally. The Main LLM never knows which specific tools
a sub-agent uses.

```
[CAPABILITIES — delegate complex or multi-step tasks]
- research      : Web research, URL reading, multi-source synthesis
- communication : Email reading, searching, summarizing, drafting replies
- productivity  : Document generation (Word, PDF, Markdown), code execution
- data          : Data analysis, spreadsheet operations, calculations
```

This is the complete extent of the Main LLM's knowledge about sub-agent work.

### Sub-Agent Tools (capability-mapped, loaded only at spawn time)

Note for current development/testing: sub-agents may run in **full-tool access mode** via
an orchestrator policy flag. In that mode, capability labels still define intent and logging,
but the spawned worker receives all registered tool schemas for rapid testing.
Production mode keeps strict capability-mapped bundles.

The capability router maps each capability to a specific set of tool IDs:

```python
CAPABILITY_ROUTING = {
    "research":      ["web_search", "url_summarizer"],
    "communication": ["email_reader"],
    "productivity":  ["doc_generator", "web_search"],
    "data":          ["data_analyzer", "web_search"],
}
```

When a sub-agent is spawned, it receives:
- JSON schemas for exactly the tools in its capability bundle
- The `report()` schema (always — it is the sub-agent's only output channel)
- The skill doc for any tool that has one (loaded at spawn time, not before)
- Nothing else

Sub-agents do not receive memory tool schemas. Memory writes happen through the Main LLM's
direct tool calls and through the summarizer after a session closes.

### Summary Table

| Tool | Main LLM | Sub-agent: research | Sub-agent: communication | Sub-agent: productivity |
|------|:---:|:---:|:---:|:---:|
| web_search | ✓ | ✓ | — | ✓ |
| url_summarizer | — | ✓ | — | — |
| memory_search | ✓ | — | — | — |
| memory_save | ✓ | — | — | — |
| memory_update | ✓ | — | — | — |
| email_reader | — | — | ✓ | — |
| doc_generator | — | — | — | ✓ |
| report() | — | ✓ | ✓ | ✓ |

---

## 4. The Directive System

The Main LLM communicates control decisions to the supervisor by writing directive blocks
in its response. The supervisor parses and strips these before anything reaches the user.
The user never sees directive text.

### [DELEGATE] — start a sub-agent task

```
[DELEGATE]
task: <complete self-contained description — include ALL context, names, dates, constraints.
      The sub-agent has no access to conversation history.>
capability: <one or more capability names, comma-separated>
```

The supervisor maps the capability to tool IDs and spawns a worker.

### [STOP] — cancel a running task

```
[STOP]
task_id: <id>
```

### [ANSWER_TO] — send user input to a paused task

```
[ANSWER_TO]
task_id: <id>
answer: <the user's answer>
```

### [MODE_SWITCH] — switch Vayumi between conversation and meeting mode

```
[MODE_SWITCH]
mode: meeting
```
or
```
[MODE_SWITCH]
mode: conversation
```

The supervisor intercepts this and sends the `mode_switch` websocket message to Vayumi.
Mode switching is the Main LLM's decision because only it knows the user's intent from
context. The user might say "let's record this meeting" or "let's go back to talking."

---

## 5. Vayumi Integration

### respond_via and interrupt_policy

Every response the supervisor sends back through Vayumi must include `respond_via` and
`interrupt_policy`. These are not optional. The supervisor decides them based on how the
turn arrived.

| Turn source | respond_via | interrupt_policy |
|-------------|-------------|-----------------|
| Voice command (wake word path) | `voice_and_chat` | `replace` |
| Typed chat (chatbot_message or POST /chat) | `chat_only` | `queue` |
| Sub-agent DONE notification (proactive) | `chat_only` | `queue` |
| Urgent system alert | `voice_and_chat` | `replace` |

The Vayumi context dict passed to `handle_turn` includes an `input_mode` field
(`voice` or `chat`) so the supervisor can determine the correct values automatically.

### Mode Switching

When the supervisor receives `[MODE_SWITCH]` from the Main LLM:

1. Supervisor sends `{"type": "mode_switch", "mode": "meeting"}` to Vayumi via websocket.
2. Supervisor waits for `mode_changed` ack from Vayumi.
3. Supervisor updates its own `session_mode` state.
4. Supervisor switches the Main LLM's turn handling behavior (see Meeting Mode section).

Switching back to conversation mode follows the same path with `mode: conversation`.

### Interrupt Handling

Vayumi calls `AgentRunner.cancel()` when:
- The user says the wake word while the AI is speaking (live wake interrupt)
- The user sends an explicit `interrupt` websocket message

What the supervisor does on interrupt:

1. Sets `interrupt_store.set_interrupted(session_id, True)`.
2. The streaming loop in `handle_turn` checks this flag and stops yielding chunks.
3. Any `directive_buffer` that was being built is discarded — incomplete directives must
   not trigger actions.
4. Sub-agent workers are not touched. They keep running.
5. Vayumi handles `interrupt_ack` and resume policy tracking internally and emits them
   to the client.

When the next turn arrives after an interrupt:
- `interrupt_store.clear(session_id)`
- The supervisor processes normally
- Sub-agent signals accumulated during the interrupted turn are drained at the start
- If the user says "continue" or "go on" — the Main LLM writes a reply and the supervisor
  calls `POST /session/{session_id}/resume` on Vayumi to resume TTS from the checkpoint
- If the user says something new — the supervisor starts a fresh turn normally

The supervisor queries `GET /session/{session_id}/status` at the start of each turn to get
Vayumi's current state: `is_ai_speaking`, `mode`, `voice_source`. This is passed into the
Main LLM's per-turn context injection so it can make aware decisions.

### Meeting Mode Behavior

In meeting mode, Vayumi sends `diarization_segment` and `transcription_final` events
continuously as the meeting proceeds. The orchestrator does NOT call the Main LLM for every
segment — that would be wasteful and noisy.

The supervisor maintains a `meeting_buffer` per session:

```python
@dataclass
class MeetingBuffer:
    session_id: str
    segments: list[dict]    # accumulated diarization_segment events
    transcript_lines: list[str]  # accumulated speaker: text lines
    start_time: float
```

In meeting mode, for each incoming `transcription_final` event:
- The supervisor appends the segment to `meeting_buffer`
- No LLM call is made unless the user explicitly asks something

When the user explicitly asks something (via chatbot_message or voice command in meeting mode):
- The supervisor injects `meeting_buffer.transcript_lines` as a context block into the
  Main LLM's per-turn context alongside the normal memory context
- Main LLM answers with full awareness of what was said in the meeting

When the user switches back to conversation mode:
- The meeting buffer is summarized and saved to MemoryOS
- The buffer is cleared

```
[MEETING TRANSCRIPT — current session]
Speaker A (0:00): Let's discuss the Q3 roadmap.
Speaker B (0:12): I think we should prioritize the mobile release first.
...
```

---

## 6. Conversation History and Context Window Management

The Main LLM's conversation history is maintained externally by `history_store.py`. It is
passed in as part of `update_context` each turn. The 32k context window requires active
management over long sessions.

### Constants

```python
COMPRESSION_TRIGGER = 20_000   # tokens — start compressing when history exceeds this
KEEP_RECENT_TURNS = 6          # always keep last N user/assistant pairs verbatim
```

### Three-Stage Messages List

The `messages` list passed to `update_context` on every turn has three stages:

```
Stage 1 — Developer prompt (fixed for the session)
  Base instructions, user profile, 4 direct tool schemas, capability menu,
  directive format instructions

Stage 2 — Per-turn context (rebuilt every turn)
  Memory search results for this transcript
  Active tasks block (running/paused sub-agents)
  Completed task results from this turn
  Vayumi session state (mode, is_ai_speaking)
  Meeting transcript buffer (only in meeting mode)

Stage 3 — Turn history (managed by history_store)
  [EARLIER CONVERSATION SUMMARY]   ← present only after compression has run
  user turn N
  assistant turn N
  user turn N+1
  assistant turn N+1
  ...  (last KEEP_RECENT_TURNS pairs verbatim)
```

### Compression Algorithm

Compression runs at the start of each turn before building messages. It is synchronous
because the compressed history must be ready before `update_context` is sent.

```python
def maybe_compress(session_id: str) -> None:
    turns = history_store.get(session_id)
    if estimate_tokens(turns) < COMPRESSION_TRIGGER:
        return

    keep_n = KEEP_RECENT_TURNS * 2   # user + assistant = 2 messages per turn
    to_compress = turns[:-keep_n]
    recent = turns[-keep_n:]

    if not to_compress:
        return

    summary = _compress_turns(to_compress)    # short LiteRT call, 3-5 sentences

    history_store.set(session_id, [
        {"role": "system", "content": [{"type": "text",
            "text": f"[EARLIER CONVERSATION SUMMARY]\n{summary}"}]}
    ] + recent)

    # Save key facts from the compressed turns to MemoryOS (background)
    asyncio.create_task(summarizer.run_on_turns(speaker_id, to_compress))
```

`_compress_turns` uses a short-lived LiteRT Engine call (no tools, one inference, 3-5
sentence output). It does not share the Main LLM or sub-agent workers.

Token estimation uses character count divided by 4, which is accurate enough to trigger
compression reliably without calling the model.

---

## 7. File Structure

```
orchestrator/
    __init__.py
    supervisor.py          # Entry point — Vayumi calls this. Owns the main turn loop.
    main_agent.py          # Main LLM worker process: parse-execute-inject loop + UX events
    sub_agent.py           # Sub-agent worker process: task loop, report() as JSON schema
    session_store.py       # Active sub-agent sessions per speaker_id
    history_store.py       # Main LLM turn history per session + compression
    meeting_store.py       # Meeting buffer per session (transcript accumulation)
    signal_bus.py          # mp.Queue per speaker_id — sub-agents write, supervisor reads
    prompt_builder.py      # ALL prompt and schema assembly — nothing else builds prompts
    capability_router.py   # CAPABILITY_ROUTING table + resolve()
    directive_parser.py    # Parses [DELEGATE], [STOP], [ANSWER_TO], [MODE_SWITCH]
    function_parser.py     # Parses <start_function_call>...<end_function_call> tags
    summarizer.py          # Post-session and turn-compression memory extraction
    context_loader.py      # Skill doc loading, reads registry
    worker_base.py         # LiteRTWorker class: mp.Process + req/resp queues
    ux_emitter.py          # All user-facing status event construction

tools/
    __init__.py            # TOOL_REGISTRY: fn + schema + metadata for every tool
    web_search.py          # Tavily wrapper
    url_summarizer.py
    email_reader.py
    doc_generator.py
    memory_ops.py          # memory_search, memory_save, memory_update (Main LLM only)

skills/
    email_reader.md        # Loaded only for sub-agents with email_reader in bundle
    doc_generator.md
    web_research.md
    # one .md per tool that needs multi-step instructions
```

---

## 8. The Tool Registry (tools/__init__.py)

Every tool has a Python function and a JSON schema registered together.

```python
TOOL_REGISTRY = {
    "web_search": {
        "fn": web_search_fn,
        "schema": {
            "type": "function",
            "function": {
                "name": "web_search",
                "description": "Search the web for current information.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string",
                                  "description": "Search query, 3-8 words"}
                    },
                    "required": ["query"]
                }
            }
        },
        "has_skill_doc": False,
        "main_llm_direct": True,
    },
    "email_reader": {
        "fn": email_reader_fn,
        "schema": { ... },
        "has_skill_doc": True,
        "main_llm_direct": False,
    },
    "memory_search": {
        "fn": memory_search_fn,
        "schema": { ... },
        "has_skill_doc": False,
        "main_llm_direct": True,
    },
    # ... all other tools follow same structure
}

def get_schemas_for_main_llm() -> list[dict]:
    return [v["schema"] for v in TOOL_REGISTRY.values() if v["main_llm_direct"]]

def get_schemas_for_task(tool_ids: list[str]) -> list[dict]:
    return [TOOL_REGISTRY[tid]["schema"] for tid in tool_ids if tid in TOOL_REGISTRY]

def execute_function(name: str, params: dict) -> str:
    if name not in TOOL_REGISTRY:
        return f"ERROR: Unknown function {name}"
    try:
        return str(TOOL_REGISTRY[name]["fn"](**params))
    except Exception as e:
        return f"ERROR: {e}"
```

Tool functions have no knowledge of sessions, users, or the orchestrator. They receive
typed arguments and return a string. Credentials come from `os.environ`.

---

## 9. The Capability Router (capability_router.py)

```python
CAPABILITY_ROUTING: dict[str, list[str]] = {
    "research":      ["web_search", "url_summarizer"],
    "communication": ["email_reader"],
    "productivity":  ["doc_generator", "web_search"],
    "data":          ["data_analyzer", "web_search"],
}

CAPABILITY_MENU = """[CAPABILITIES — delegate complex or multi-step tasks]
- research      : Web research, URL reading, multi-source synthesis
- communication : Email reading, searching, summarizing threads
- productivity  : Document generation (Word, PDF, Markdown), code execution
- data          : Data analysis, spreadsheet operations, calculations
"""

def resolve(capabilities: list[str]) -> list[str]:
    """Return deduplicated tool IDs for the given capability names."""
    seen = []
    for cap in capabilities:
        for tid in CAPABILITY_ROUTING.get(cap, []):
            if tid not in seen:
                seen.append(tid)
    return seen
```

To add a new capability: one line in `CAPABILITY_ROUTING`, one line in `CAPABILITY_MENU`.
To add a tool to an existing capability: append the tool ID to that capability's list.

---

## 10. The Prompt Builder (prompt_builder.py)

All prompt construction lives here. No other file builds prompts.

### Main LLM Developer Prompt (built once per session)

```python
def build_main_developer_prompt(speaker_id: str, user_model: dict) -> str:
    return f"""You are a helpful, personalized assistant.

[SESSION]
Speaker: {speaker_id}

[USER PROFILE]
{personalization.to_system_prompt(user_model)}

[YOUR DIRECT TOOLS]
Call these for instant, single-step tasks.
Format: <start_function_call>call:name{{key:value}}<end_function_call>
{json.dumps(get_schemas_for_main_llm(), indent=2)}

{CAPABILITY_MENU}

[DIRECTIVES]
For multi-step tasks, or tasks under a capability above, write a directive block.
Directives are parsed by the system and never shown to the user.
Write your reply to the user separately from any directive.

Start a delegated task:
[DELEGATE]
task: <self-contained description with ALL context — sub-agent has no conversation history>
capability: <capability name(s), comma-separated>

Cancel a running task:
[STOP]
task_id: <id>

Send user input to a paused task:
[ANSWER_TO]
task_id: <id>
answer: <the answer>

Switch conversation/meeting mode:
[MODE_SWITCH]
mode: <conversation or meeting>
"""
```

### Per-Turn Context Message (rebuilt every turn, injected as second message)

```python
def build_turn_context(mem_context: str, active_tasks: str,
                       pending_results: list[dict],
                       vayumi_state: dict,
                       meeting_transcript: str | None) -> dict:
    parts = []
    if mem_context:
        parts.append(f"[MEMORY]\n{mem_context}")
    if active_tasks:
        parts.append(active_tasks)
    if pending_results:
        lines = []
        for r in pending_results:
            tag = "completed" if r["type"] == "DONE" else "failed"
            lines.append(f'Task "{r["description"]}" {tag}: {r["message"]}')
        parts.append("[TASK RESULTS THIS TURN]\n" + "\n".join(lines))
    if vayumi_state:
        parts.append(
            f"[SESSION STATE]\n"
            f"mode: {vayumi_state.get('mode','conversation')}\n"
            f"is_ai_speaking: {vayumi_state.get('is_ai_speaking', False)}"
        )
    if meeting_transcript:
        parts.append(f"[MEETING TRANSCRIPT — current session]\n{meeting_transcript}")
    return {"role": "system",
            "content": [{"type": "text", "text": "\n\n".join(parts)}]}
```

### Sub-Agent Developer Prompt (built at spawn time)

```python
def build_sub_agent_prompt(task_id: str, task_description: str,
                            tool_ids: list[str], skill_doc: str | None,
                            max_steps: int) -> str:
    schemas = get_schemas_for_task(tool_ids) + [REPORT_SCHEMA]
    schema_block = json.dumps(schemas, indent=2)
    skill_section = f"\n\n[SKILL REFERENCE]\n{skill_doc}" if skill_doc else ""

    return f"""You are a task executor. You do not talk to the user.
Your only output is through the report() function.
Never write plain text. Always call a function.

TASK ID: {task_id}
TASK: {task_description}

RULES:
- report(STEP, ...) after each meaningful action
- report(NEEDS_INFO, question) if you need user input to continue
- report(DONE, summary) when finished — include what was done and where the result is
- report(ERROR, reason) if unrecoverable
- report(CAPABILITY_GAP, what is missing) if task cannot be done with available tools
- Maximum {max_steps} total function calls including report()
- If an approach fails twice, report ERROR
- Write self-contained messages in report() — the main agent has no view of your steps

FUNCTIONS:
{schema_block}{skill_section}"""
```

---

## 11. The report() Schema (sub_agent.py)

```python
REPORT_SCHEMA = {
    "type": "function",
    "function": {
        "name": "report",
        "description": (
            "Your only output channel. Always call this when done, blocked, or on error. "
            "Never write a plain-text final answer."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "description": (
                        "STEP: progress update. "
                        "DONE: task complete, include result location. "
                        "NEEDS_INFO: blocked, include exact question for user. "
                        "ERROR: failed, include reason. "
                        "CAPABILITY_GAP: tools insufficient, include what is missing."
                    )
                },
                "message": {
                    "type": "string",
                    "description": "Clear description appropriate to the status."
                }
            },
            "required": ["status", "message"]
        }
    }
}
```

---

## 12. The Main LLM Worker (main_agent.py)

One long-lived process per session. Holds one Engine and one Conversation.

```python
def _main_llm_worker(model_path, cache_dir, initial_messages, req_q, resp_q):
    import litert_lm
    from tools import execute_function
    from function_parser import parse_function_call, extract_text

    litert_lm.set_min_log_severity(litert_lm.LogSeverity.ERROR)
    current_messages = initial_messages

    with litert_lm.Engine(str(model_path), backend=litert_lm.Backend.CPU,
                          cache_dir=str(cache_dir)) as engine:
        conv_ctx = engine.create_conversation(messages=current_messages)
        conversation = conv_ctx.__enter__()

        while True:
            req = req_q.get()
            if req.get("cmd") == "stop":
                break

            if req.get("cmd") == "update_context":
                # Rebuilds conversation with fresh messages list each turn.
                # Full turn history is included in req["messages"].
                conv_ctx.__exit__(None, None, None)
                current_messages = req["messages"]
                conv_ctx = engine.create_conversation(messages=current_messages)
                conversation = conv_ctx.__enter__()
                resp_q.put({"ok": True})

            elif req.get("cmd") == "chat":
                _run_main_loop(conversation, req["message"], resp_q, execute_function)

        conv_ctx.__exit__(None, None, None)


def _run_main_loop(conversation, user_message, resp_q, execute_fn):
    from function_parser import parse_function_call, extract_text

    current_input = user_message
    MAX_TOOL_CALLS = 6

    try:
        for _ in range(MAX_TOOL_CALLS + 1):
            full_text = ""

            for chunk in conversation.send_message_async(current_input):
                text = extract_text(chunk)
                if text:
                    full_text += text
                    # Stream only non-function-call text
                    if "<start_function_call>" not in full_text:
                        resp_q.put({"ok": True, "event": "chunk", "text": text})

            if "<start_function_call>" not in full_text:
                resp_q.put({"ok": True, "event": "done"})
                return

            call = parse_function_call(full_text)
            if not call["success"]:
                resp_q.put({"ok": True, "event": "done"})
                return

            fn, params = call["function_name"], call["params"]

            # UX: emit before executing so user sees it instantly
            resp_q.put({"ok": True, "event": "tool_status",
                        "phase": "start", "tool": fn, "params": params})

            result = execute_fn(fn, params)

            resp_q.put({"ok": True, "event": "tool_status",
                        "phase": "done", "tool": fn})

            current_input = {"role": "user", "content": [
                {"type": "text", "text": f"[TOOL RESULT for {fn}]: {result}"}]}

        resp_q.put({"ok": True, "event": "done"})

    except Exception as e:
        resp_q.put({"ok": False, "error": str(e)})
```

---

## 13. The Sub-Agent Worker (sub_agent.py)

One process per active task. Gets only its capability-mapped schemas. Communicates only
via `report()`.

```python
def _sub_agent_worker(model_path, cache_dir, task_id, developer_prompt,
                      tool_ids, signal_q, req_q, resp_q):
    import litert_lm
    from tools import execute_function
    from function_parser import parse_function_call, extract_text

    litert_lm.set_min_log_severity(litert_lm.LogSeverity.ERROR)
    step_log = []
    step_count = 0
    MAX_STEPS = 12

    messages = [{"role": "developer",
                 "content": [{"type": "text", "text": developer_prompt}]}]

    with litert_lm.Engine(str(model_path), backend=litert_lm.Backend.CPU,
                          cache_dir=str(cache_dir)) as engine:
        with engine.create_conversation(messages=messages) as conversation:

            while True:
                req = req_q.get()

                if req.get("cmd") == "stop":
                    step_log.append("[STOPPED]")
                    signal_q.put({"type": "ERROR", "task_id": task_id,
                                  "message": "Cancelled", "step_log": step_log})
                    break

                if req.get("cmd") == "run":
                    current_input = req["message"]
                    done = False

                    while not done and step_count < MAX_STEPS:
                        step_count += 1
                        try:
                            response = conversation.send_message(current_input)
                            text = extract_text(response)
                        except Exception as e:
                            signal_q.put({"type": "ERROR", "task_id": task_id,
                                          "message": str(e), "step_log": step_log})
                            resp_q.put({"ok": False, "error": str(e)})
                            done = True
                            break

                        if "<start_function_call>" not in text:
                            # Model wrote plain text — prompt it to use report()
                            step_log.append(f"[TEXT_LEAK] {text[:80]}")
                            current_input = {"role": "user", "content": [{"type": "text",
                                "text": "Use report() to communicate. Do not write plain text."}]}
                            continue

                        call = parse_function_call(text)
                        if not call["success"]:
                            step_log.append("[PARSE_FAIL]")
                            break

                        fn, params = call["function_name"], call["params"]
                        step_log.append(f"[CALL] {fn}({params})")

                        # Emit STEP signal for every non-report tool call
                        if fn != "report":
                            signal_q.put({"type": "STEP", "task_id": task_id,
                                          "message": f"Using {fn}", "tool": fn})

                        if fn == "report":
                            status = params.get("status", "STEP")
                            message = params.get("message", "")
                            step_log.append(f"[REPORT:{status}] {message}")
                            signal_q.put({
                                "type": status, "task_id": task_id, "message": message,
                                "step_log": step_log if status in
                                    ("DONE", "ERROR", "CAPABILITY_GAP") else []
                            })
                            if status in ("DONE", "ERROR", "CAPABILITY_GAP"):
                                resp_q.put({"ok": True, "event": "done"})
                                done = True
                                break
                            if status == "NEEDS_INFO":
                                current_input = {"role": "user", "content": [
                                    {"type": "text", "text": "Awaiting user response."}]}
                                resp_q.put({"ok": True, "event": "paused"})
                                done = True   # break inner loop, wait for next run cmd
                                break
                            # STEP — acknowledge and continue
                            current_input = {"role": "user", "content": [
                                {"type": "text", "text": "Noted. Continue."}]}
                            continue

                        # Real tool execution
                        result = execute_function(fn, params)
                        current_input = {"role": "user", "content": [
                            {"type": "text",
                             "text": f"[TOOL RESULT for {fn}]: {result}"}]}

                    if step_count >= MAX_STEPS and not done:
                        step_log.append("[LIMIT]")
                        signal_q.put({"type": "ERROR", "task_id": task_id,
                                      "message": "Hit maximum step limit.",
                                      "step_log": step_log})
                        resp_q.put({"ok": True, "event": "done"})
```

---

## 14. The Signal Bus (signal_bus.py)

One `mp.Queue` per `speaker_id`. Sub-agent workers put signals in. Supervisor drains at
the start of each turn — non-blocking.

```python
class SignalBus:
    def __init__(self):
        self._queues: dict[str, mp.Queue] = {}

    def get_queue(self, speaker_id: str) -> mp.Queue:
        if speaker_id not in self._queues:
            self._queues[speaker_id] = mp.Queue()
        return self._queues[speaker_id]

    def drain(self, speaker_id: str) -> list[dict]:
        q = self.get_queue(speaker_id)
        out = []
        while True:
            try:
                out.append(q.get_nowait())
            except Exception:
                break
        return out

signal_bus = SignalBus()
```

Signal routing:

| Signal | Action |
|--------|--------|
| STEP | Update task status + last_step_message. Emit task_progress UX event immediately. |
| DONE | Add to pending_results. Launch summarizer. Close worker. |
| NEEDS_INFO | Mark task paused. Store question. Appear in active_tasks block. |
| ERROR | Add to pending_results. Launch summarizer. Close worker. |
| CAPABILITY_GAP | Add to pending_results. Main LLM decides how to respond. |

---

## 15. The Session Store (session_store.py)

```python
@dataclass
class TaskSession:
    task_id: str
    description: str
    capability: str
    status: str                    # running | paused | done | error
    tool_ids: list[str]
    worker: LiteRTWorker
    pending_question: str | None
    step_log: list[str]
    last_step_message: str
    created_at: float
    step_count: int
    max_steps: int
    timeout_at: float
```

```python
def get_active_tasks_block(speaker_id: str) -> str:
    tasks = self._tasks.get(speaker_id, {})
    if not tasks:
        return ""
    lines = ["[ACTIVE TASKS]"]
    for t in tasks.values():
        if t.status == "running":
            step = f"(last: {t.last_step_message})" if t.last_step_message else ""
            lines.append(f'{t.task_id}: "{t.description}" — running {step}')
        elif t.status == "paused":
            lines.append(
                f'{t.task_id}: "{t.description}" — paused, '
                f'waiting for: "{t.pending_question}"')
        elif t.status == "done":
            lines.append(f'{t.task_id}: "{t.description}" — done')
    return "\n".join(lines)
```

---

## 16. The UX Emitter (ux_emitter.py)

All user-visible event construction in one file.

```python
def tool_start(tool: str, params: dict) -> dict:
    labels = {
        "web_search":     lambda p: f"Searching for \"{p.get('query','')}\"…",
        "memory_search":  lambda p: "Checking memory…",
        "memory_save":    lambda p: "Saving to memory…",
        "memory_update":  lambda p: "Updating memory…",
        "url_summarizer": lambda p: f"Reading {p.get('url','page')}…",
    }
    label = labels.get(tool, lambda p: f"Using {tool}…")(params)
    return {"ok": True, "event": "tool_status", "phase": "start",
            "tool": tool, "display": label}

def tool_done(tool: str) -> dict:
    return {"ok": True, "event": "tool_status", "phase": "done", "tool": tool}

def task_progress(task_id: str, desc: str, step: str) -> dict:
    return {"event": "task_progress", "task_id": task_id,
            "task_description": desc, "step": step}

def task_complete(task_id: str, desc: str, summary: str) -> dict:
    return {"event": "task_complete", "task_id": task_id,
            "task_description": desc, "summary": summary}

def task_waiting(task_id: str, desc: str, question: str) -> dict:
    return {"event": "task_waiting", "task_id": task_id,
            "task_description": desc, "question": question}

def task_error(task_id: str, desc: str, reason: str) -> dict:
    return {"event": "task_error", "task_id": task_id,
            "task_description": desc, "reason": reason}
```

---

## 17. The Summarizer (summarizer.py)

Runs as a background asyncio task. Two jobs: post-session task summary and turn-history
compression extraction. Uses a short-lived Engine each time — never shares main or
sub-agent workers.

```python
async def run_on_task(speaker_id, task_description, result, step_log):
    prompt = (
        "Extract only the facts, decisions, and file locations worth storing in "
        "long-term memory from this completed task. Ignore failed attempts and "
        "intermediate tool steps.\n\n"
        f"Task: {task_description}\nResult: {result}\n"
        f"Log:\n{chr(10).join(step_log[-20:])}\n\n"
        'Output JSON only: [{"type":"fact|preference|event|file","content":"..."}]'
    )
    await _run(speaker_id, prompt)

async def run_on_turns(speaker_id, turns):
    text = "\n".join(f"{t['role'].upper()}: {extract_text(t)}" for t in turns)
    prompt = (
        "Extract the important facts, preferences, and decisions from this "
        "conversation worth storing long-term.\n\n"
        f"{text}\n\n"
        'Output JSON only: [{"type":"fact|preference|event|file","content":"..."}]'
    )
    await _run(speaker_id, prompt)

async def _run(speaker_id, prompt):
    try:
        with litert_lm.Engine(MODEL_PATH, backend=litert_lm.Backend.CPU,
                              cache_dir=CACHE_DIR) as engine:
            with engine.create_conversation(
                messages=[{"role": "developer",
                           "content": [{"type": "text", "text": prompt}]}]
            ) as conv:
                response = conv.send_message({"role": "user", "content": [
                    {"type": "text", "text": "Extract now."}]})
                items = json.loads(extract_text(response))
                for item in items:
                    mem.save(item["content"],
                             MemoryType[item["type"].upper()],
                             speaker_id=speaker_id)
    except Exception:
        pass  # best-effort, never block
```

---

## 18. The Supervisor (supervisor.py)

The only file Vayumi touches directly.

```python
async def handle_turn(transcript: str, session_id: str, context: dict):
    """
    Called by AgentRunner.run().
    context includes: speaker_id, input_mode ("voice"|"chat"), vayumi_state dict.
    Yields Vayumi event dicts.
    """
    speaker_id = context["speaker_id"]
    input_mode = context.get("input_mode", "chat")
    vayumi_state = context.get("vayumi_state", {})
    session_mode = session_mode_store.get(session_id, "conversation")

    # Determine respond_via and interrupt_policy from input mode
    respond_via = "voice_and_chat" if input_mode == "voice" else "chat_only"
    interrupt_policy = "replace" if input_mode == "voice" else "queue"

    # 1. Compress history if needed
    history_store.maybe_compress(session_id)

    # 2. Drain sub-agent signals
    signals = signal_bus.drain(speaker_id)
    pending_results = []

    for sig in signals:
        task = session_store.get(speaker_id, sig["task_id"])
        if not task:
            continue
        if sig["type"] == "STEP":
            session_store.update_step(speaker_id, sig["task_id"], sig["message"])
            yield ux_emitter.task_progress(sig["task_id"], task.description, sig["message"])
        elif sig["type"] == "NEEDS_INFO":
            session_store.mark_paused(speaker_id, sig["task_id"], sig["message"])
            yield ux_emitter.task_waiting(sig["task_id"], task.description, sig["message"])
            pending_results.append(sig)
        elif sig["type"] in ("DONE", "ERROR", "CAPABILITY_GAP"):
            session_store.mark_closed(speaker_id, sig["task_id"])
            if sig["type"] == "DONE":
                yield ux_emitter.task_complete(sig["task_id"], task.description, sig["message"])
            else:
                yield ux_emitter.task_error(sig["task_id"], task.description, sig["message"])
            pending_results.append(sig)
            asyncio.create_task(summarizer.run_on_task(
                speaker_id, task.description, sig["message"], sig.get("step_log", [])))
            session_store.stop_and_remove(speaker_id, sig["task_id"])

    # In meeting mode: accumulate transcript, only call Main LLM if user asks something
    if session_mode == "meeting":
        meeting_store.append(session_id, transcript)
        if not _is_explicit_question(transcript):
            return  # just accumulate, no LLM call

    # 3. Memory search
    mem_context = mem.search(transcript, speaker_id=speaker_id).context

    # 4. Build updated messages for Main LLM
    meeting_transcript = meeting_store.get_formatted(session_id) if session_mode == "meeting" else None
    updated_messages = prompt_builder.build_main_messages(
        session_id=session_id, speaker_id=speaker_id,
        mem_context=mem_context,
        active_tasks=session_store.get_active_tasks_block(speaker_id),
        pending_results=pending_results,
        vayumi_state=vayumi_state,
        meeting_transcript=meeting_transcript,
    )
    main_worker = main_worker_store.get(session_id)
    main_worker.request({"cmd": "update_context", "messages": updated_messages})

    # 5. Stream Main LLM response
    yield {"event": "agent_thinking"}
    full_response = ""
    directive_buffer = ""
    interrupted = False

    for chunk in main_worker.stream({"cmd": "chat",
                                     "message": _as_user_msg(transcript)}):
        if interrupt_store.is_interrupted(session_id):
            interrupted = True
            directive_buffer = ""   # discard any incomplete directive on interrupt
            break

        if not chunk.get("ok"):
            yield {"event": "error", "message": chunk.get("error", "")}
            return

        ev = chunk.get("event")
        if ev == "tool_status":
            # Pass UX tool events straight through — Vayumi shows these to the user
            phase = chunk["phase"]
            tool = chunk["tool"]
            if phase == "start":
                yield ux_emitter.tool_start(tool, chunk.get("params", {}))
            else:
                yield ux_emitter.tool_done(tool)

        elif ev == "chunk":
            text = chunk["text"]
            if _is_directive_start(text) or directive_buffer:
                directive_buffer += text
            else:
                full_response += text
                yield {"event": "agent_response_chunk", "text": text,
                       "respond_via": respond_via,
                       "interrupt_policy": interrupt_policy}

        elif ev == "done":
            break

    if not interrupted:
        yield {"event": "agent_response_end"}
        yield {"event": "chatbot_response", "text": full_response,
               "respond_via": respond_via, "interrupt_policy": interrupt_policy}

    # 6. Parse and execute directives
    for d in directive_parser.parse(directive_buffer):
        if d["type"] == "DELEGATE":
            _spawn_sub_agent(speaker_id, d)
        elif d["type"] == "STOP":
            _stop_sub_agent(speaker_id, d["task_id"])
        elif d["type"] == "ANSWER_TO":
            _resume_sub_agent(speaker_id, d["task_id"], d["answer"])
        elif d["type"] == "MODE_SWITCH":
            await _handle_mode_switch(session_id, speaker_id, d["mode"])

    # 7. Store turn + async memory flush
    if not interrupted:
        history_store.append(session_id, transcript, full_response)
    mem.add_turn(speaker_id, transcript)
    asyncio.create_task(_flush_memory(speaker_id))


async def handle_interrupt(session_id: str) -> None:
    """Called by AgentRunner.cancel()."""
    interrupt_store.set_interrupted(session_id, True)
    # Sub-agent workers are not touched — they keep running.
    # Vayumi handles interrupt_ack and resume policy tracking internally.
    # directive_buffer is discarded inside handle_turn when the flag is seen.


async def _handle_mode_switch(session_id: str, speaker_id: str, mode: str) -> None:
    # Send mode_switch to Vayumi via the session's websocket
    await vayumi_ws_send(session_id, {"type": "mode_switch", "mode": mode})
    # Update local state
    session_mode_store.set(session_id, mode)
    if mode == "meeting":
        meeting_store.init(session_id)
    else:
        # Save meeting transcript to memory before clearing
        transcript_lines = meeting_store.get_formatted(session_id)
        if transcript_lines:
            asyncio.create_task(summarizer.run_on_turns(speaker_id,
                [{"role": "user", "content": [{"type": "text", "text": transcript_lines}]}]))
        meeting_store.clear(session_id)


def _spawn_sub_agent(speaker_id: str, directive: dict) -> None:
    task_id = _generate_task_id()
    capabilities = [c.strip() for c in directive["capability"].split(",")]
    tool_ids = capability_router.resolve(capabilities)
    if not tool_ids:
        return   # unknown capability — do nothing, no crash
    skill_doc = context_loader.load_skill_docs(tool_ids)
    developer_prompt = prompt_builder.build_sub_agent_prompt(
        task_id, directive["task"], tool_ids, skill_doc, max_steps=12)
    worker = LiteRTWorker(
        worker_fn=_sub_agent_worker,
        worker_args=(MODEL_PATH, CACHE_DIR, task_id, developer_prompt,
                     tool_ids, signal_bus.get_queue(speaker_id))
    )
    worker.start()
    session_store.add(speaker_id, TaskSession(
        task_id=task_id, description=directive["task"],
        capability=directive["capability"], status="running",
        tool_ids=tool_ids, worker=worker, pending_question=None,
        step_log=[], last_step_message="",
        created_at=time.time(), step_count=0, max_steps=12,
        timeout_at=time.time() + 120,
    ))
    worker.request({"cmd": "run", "message": {"role": "user",
        "content": [{"type": "text", "text": "Begin the task now."}]}})
```

---

## 19. MemoryOS Integration

| Where | Operation | When |
|-------|-----------|------|
| Supervisor, start of turn | `mem.search(transcript)` | Every turn |
| Main LLM, via parse-execute | `memory_search`, `memory_save`, `memory_update` | When model calls these tools |
| Supervisor, end of turn (async) | `mem.add_turn(speaker_id, transcript)` | Every turn |
| Supervisor, end of turn (async) | `mem.flush_session()` | Every turn |
| Summarizer (async), post sub-agent | `mem.save(fragment)` per item | After every sub-agent session closes |
| Summarizer (async), post compression | `mem.save(fragment)` per item | After each history compression |
| Mode switch out of meeting (async) | `mem.save` via summarizer | When switching from meeting to conversation |

Sub-agents do not write to MemoryOS directly.

---

## 20. Complete Flow Examples

### Example A — Voice command, direct tool use

User (voice): "What's the latest on AI regulation?"

```
input_mode = "voice" → respond_via = "voice_and_chat", interrupt_policy = "replace"

1. Compress check → no action
2. Drain signals → empty
3. mem.search → no relevant memories
4. update_context pushed
5. Main LLM calls web_search
6. Worker emits tool_status{start} → Vayumi shows "Searching for 'AI regulation'…"
7. web_search runs
8. Worker emits tool_status{done}
9. Main LLM streams reply → yields agent_response_chunk with respond_via=voice_and_chat
10. Vayumi speaks the answer + shows it in chat
```

### Example B — Typed chat, sub-agent task

User (typed): "Find all emails from John about invoice #4421."

```
input_mode = "chat" → respond_via = "chat_only", interrupt_policy = "queue"

1. Main LLM streams: "I'll search your emails now."
   Then outputs directive:
   [DELEGATE]
   task: Find all emails from John Smith about invoice #4421. Summarize key points.
         John Smith is the billing contact. Invoice #4421 is for the March shipment.
   capability: communication

2. Supervisor: capability_router.resolve(["communication"]) → ["email_reader"]
   skill_doc loaded from skills/email_reader.md
   Sub-agent spawned with email_reader schema + report() schema + skill doc

3. Sub-agent calls email_reader tool
   → emits STEP signal → supervisor emits task_progress to Vayumi
   → Vayumi shows "[📧 Searching emails…]" in background

4. Sub-agent calls report(DONE, "3 emails found. Summary: ...")
5. Next turn: supervisor drains DONE
   → emits task_complete to Vayumi
   → adds result to pending_results
   → Main LLM tells user the summary
6. Summarizer saves "Invoice #4421 resolved March 12" to MemoryOS
```

### Example C — User switches to meeting mode

User (voice): "Let's start recording this meeting."

```
1. Main LLM writes:
   Sure, switching to meeting mode now.
   [MODE_SWITCH]
   mode: meeting

2. Supervisor parses [MODE_SWITCH]
   → sends {"type": "mode_switch", "mode": "meeting"} to Vayumi websocket
   → waits for mode_changed ack
   → sets session_mode = "meeting"
   → inits meeting_store for this session

3. From now on: Vayumi sends diarization_segment + transcription_final events
4. Supervisor accumulates transcript in meeting_store
5. No LLM called for each segment

User (in meeting): "Can you summarize what we've discussed so far?"
6. _is_explicit_question("Can you summarize...") → True
7. Main LLM called with meeting_transcript injected as context
8. Main LLM summarizes → streamed as reply
```

### Example D — Switch back from meeting mode

User: "That's the end of the meeting, back to normal."

```
1. Main LLM:
   Got it, switching back to conversation mode.
   [MODE_SWITCH]
   mode: conversation

2. Supervisor: save meeting transcript → summarizer runs async
   → meeting buffer cleared
   → session_mode = "conversation"
3. Normal conversation resumes
```

### Example E — Interrupt during speech, sub-agent unaffected

```
Main LLM mid-stream (responding to a question)
User says wake word → Vayumi calls handle_interrupt()
→ interrupt flag set → stream loop stops → directive_buffer discarded
→ Sub-agent (if running) keeps running completely unaffected

User: "Is that doc ready yet?"
→ New handle_turn:
  - interrupt flag cleared
  - drain signals → sub-agent DONE arrived during interrupt window
  - task_complete emitted to Vayumi
  - Main LLM context includes completed task result
  - Main LLM: "Yes, the document is ready! Here's what it covers..."
```

### Example F — User says "continue" after interrupt

```
Main LLM was mid-response when interrupted.
User: "Actually go on."

→ Supervisor detects user intent to resume from Main LLM's reply
→ Main LLM writes: "Of course, continuing..."
  [nothing else needed — Vayumi has the resumable tokens]
→ Supervisor calls POST /session/{session_id}/resume
→ Vayumi resumes TTS from the checkpoint
```

### Example G — Two tasks paused, both need info

```
[ACTIVE TASKS]
task_a1: "Write Q3 report" — paused, waiting for: "Which quarter's data?"
task_b2: "Book flight"    — paused, waiting for: "What is your departure date?"

Main LLM: "Two things need your input:
           For the Q3 report — Q2 or Q3 data?
           For the flight — what is your departure date?"

User: "Q3 data and I'm leaving March 15th."

Main LLM:
[ANSWER_TO]
task_id: a1
answer: Use Q3 data

[ANSWER_TO]
task_id: b2
answer: March 15th departure

Supervisor routes each to the correct paused worker. Both resume.
```

### Example H — Long session, compression triggers

```
After ~40 turns, estimate_tokens(history.turns) → 22,000 > 20,000 trigger
→ history_store.maybe_compress() runs
→ oldest 30 messages compressed to: "User building a voice assistant. Decided on
  FunctionGemma. Completed email integration. User prefers concise responses."
→ history replaced: [summary message] + [last 6 turn pairs verbatim]
→ summarizer.run_on_turns saves key facts to MemoryOS async
→ total history now ~8,000 tokens
→ user notices nothing
```

---

## 21. Edge Cases and Solutions

| Edge case | Solution |
|-----------|----------|
| Sub-agent writes plain text instead of report() | Prompt once to use report(). Log TEXT_LEAK. If fails twice, treat as STEP and continue. |
| Function call tag is malformed | function_parser returns {success:False}. Treat full_text as plain reply. Done. |
| Tool function raises exception | Return "ERROR: {msg}" string. Model decides to retry or report ERROR. No crash. |
| Main LLM worker process dies | is_alive() in stream loop. Emit error event. Restart worker, rebuild from history_store. |
| Sub-agent worker process dies | is_alive() in LiteRTWorker. Emit ERROR to signal_bus. Summarizer runs. Session closed. |
| Interrupt with incomplete directive_buffer | directive_buffer discarded when interrupt flag is seen. No partial directives execute. |
| DONE signal arrives mid-Main LLM stream | Stays in signal_bus. Drained at start of next turn. One-turn delay is acceptable. |
| Paused task timeout | Supervisor checks timeout_at each turn. Sends stop cmd. ERROR signal emitted. Session closed. |
| Two [DELEGATE] in one response | directive_parser returns both. Two workers spawned, both tracked. |
| [DELEGATE] with unknown capability | capability_router.resolve() returns []. Supervisor does not spawn. No crash. |
| [MODE_SWITCH] while sub-agent is running | Sub-agent keeps running. Mode switch only affects supervisor and Vayumi transport behavior. |
| Meeting mode, user asks question | _is_explicit_question() returns True. Full meeting transcript injected. Main LLM answers. |
| Compression while LiteRT busy | _compress_turns() waits for current sub-agent step to finish. Short wait, rare occurrence. |
| User says "cancel that" without task_id | Main LLM sees active_tasks block, knows all running task_ids, writes correct [STOP]. |
| History compression loses important fact | Summarizer saves key facts to MemoryOS before compression. mem.search retrieves them future turns. |
| User resumes after interrupt | Main LLM decides to say "continuing..." + supervisor calls POST /session/{id}/resume on Vayumi. |

---

## 22. Latency Strategy

| Action | How |
|--------|-----|
| Main LLM first token | Only 4 direct schemas + tiny capability menu in developer prompt |
| Tool feedback | tool_status{start} emitted BEFORE execution — user sees it instantly |
| Sub-agent progress | Every STEP emitted to Vayumi immediately, no batching |
| Memory flush | asyncio.create_task — never blocks the response stream |
| Summarizer | asyncio.create_task — never blocks the turn |
| Compression | Runs synchronously only when needed, keeps history small |
| Schema injection | Sub-agents get only their task's schemas, never all schemas |

---

## 23. Adding a New Tool

1. Create `tools/your_tool.py`. One function. Full type annotations. Precise docstring.
   Returns `str`. Credentials from `os.environ`.

2. Write a JSON schema — every parameter needs a clear `description`.

3. Register in `tools/__init__.py`:
```python
"your_tool": {
    "fn": your_tool_fn,
    "schema": { ... },
    "has_skill_doc": False,
    "main_llm_direct": False,   # True only if instant + single-step
}
```

4. Add to the right capability in `capability_router.py`:
```python
CAPABILITY_ROUTING = {
    "productivity": ["doc_generator", "web_search", "your_tool"],
}
```

5. If complex: create `skills/your_tool.md`. Set `has_skill_doc: True`.

6. Update `CAPABILITY_MENU` if the capability description should change (one line).

Nothing else changes.

---

## 24. Build Order

1. `function_parser.py` — parses function call tags, no dependencies
2. `signal_bus.py` — mp.Queue wrapper, no dependencies
3. `tools/__init__.py` + first tools — registry with fn + schema
4. `capability_router.py` — routing table + CAPABILITY_MENU
5. `session_store.py` — TaskSession dataclass, no LLM
6. `history_store.py` — turn history + compression
7. `meeting_store.py` — meeting transcript buffer
8. `worker_base.py` — LiteRTWorker class, no LLM logic
9. `ux_emitter.py` — event constructors
10. `context_loader.py` — skill doc loading
11. `prompt_builder.py` — all prompt logic
12. `main_agent.py` — main worker with parse-execute-inject loop
13. `sub_agent.py` — sub-agent worker
14. `directive_parser.py` — parses all four directive types
15. `summarizer.py` — post-session + turn-compression extraction
16. `supervisor.py` — wires everything together

Each layer can be tested independently before wiring to Vayumi.