
You are building Vayumi Server 2 — a voice-first multi-agent assistant backend.

BEFORE writing any code, you MUST read these files in full and understand them:

1. PLAN.md — the frozen architecture. Every decision is here. Do not invent alternatives.
2. doc/roadmap.md — the full 21-step overview so you know what comes before and after.
3. doc/history.md — what has been done so far. Do not redo completed work.
4. orchestrator_diagram_v3.drawio — the architecture diagram (17 pages). Refer to the diagram pages listed in the step file.
5. doc/tracker.md — build progress + architecture flow diagrams. Update this after each step.

Rules 11–13 summary (PLAN.md v1.7 — read before implementing voice/transport/orchestrator work):

- **Rule 11:** Typed `chat` defaults to `respond_via=voice_and_chat` when the session is voice-capable (`capabilities.tts=true` in `hello`). User hears the reply and sees captions + `chat_message`. Exceptions → `chat_only`: `tts=false`, `playback=playing`, `route=none`, meeting mode, `visible=false`.
- **Rule 12:** Every TTS path goes through `begin_tts_with_echo_suppression(turn_id)` — the only function that may emit `audio_start`. Always `client_control stop_capture` before PCM; `start_capture` after delay (`SELF_ECHO_SUPPRESSION_DELAY_MS`, or `AEC_CLIENT_SUPPRESSION_DELAY_MS` when `capabilities.aec=true`). Interrupt clears the delay and resumes capture immediately.
- **Rule 13:** Call `compute_respond_via(session_state, input_kind)` at the start of every `handle_turn` (input kinds: `voice`, `chat`, `proactive`, `system`). Proactive notifier must pass `input_kind='proactive'`. Main may override with `[RESPOND_VIA chat|voice|both]`. Full table: PLAN.md §7.5.

Then determine which step to work on:
- Look at PLAN.md Section 8 (Phase plan). Find the first step with status ⬜. That is the current step.
- Read its step file: doc/step-<N>.md (where N is the step number you found).
- If a previous step exists (doc/step-<N-1>.md), read that too so you know what code already exists.
- If the step file does not exist yet, STOP and tell me. I need to create or approve the step file before you build anything.

RULES YOU MUST FOLLOW:

1. ONLY build what the step file says. If you feel tempted to add something from a later step, stop. Write it as a note for that later step instead.

2. No temporary hacks. Every line of code must be the real implementation shape even if it's a subset of the final behavior. No TODO comments that say "implement later." No placeholder functions that return hardcoded values (except the dev auth bypass which is by design). No feature flags for things not in this step.

3. Match the folder structure in PLAN.md Section 4 exactly. Same file names, same directory layout. Do not reorganize.

4. Match the function names in PLAN.md Section 7.11 exactly. When the plan says the function is called `verify_token`, name it `verify_token`. When the plan says a class is `SubAgentWorker`, name it `SubAgentWorker`. Do not rename things.

5. Use the exact dependencies from PLAN.md Section 11. Do not add new dependencies without stating why. Do not upgrade to alternatives.

6. The web client must work after your changes. If this step touches the client, test it. If this step does not touch the client, the client must still work unchanged.

7. Write tests as specified in the step file. Every step must end with a green pytest run.

8. After completing the step, run the acceptance test from the step file. List each acceptance test item and confirm pass/fail.

9. Do not modify PLAN.md, doc/roadmap.md, doc/history.md, or doc/tracker.md during implementation. Update those only in the completion phase (see below).

10. Do not commit to git unless I ask you to.

11. Keep code clean: no commented-out code, no debug prints left behind, no unused imports. Use type hints. Follow the structlog logging pattern from PLAN.md.

12. If something in the step file is ambiguous or seems wrong, ASK ME before implementing. Do not guess.
13. Dont fake anything, always see architecture carefully, need to be connected and tested with different cases the real cases not the fake one
14. If you remove anything wrong remove permanently dont make anything legacy ad leave there oaky 

ENVIRONMENT:
- Python 3.11 (`pyproject.toml`: `requires-python = ">=3.11,<3.12"`). Not 3.12.
- Activate the project venv at `Server2/venv` (`source venv/bin/activate`) and install with `pip install -e .` (or use `uv` if you prefer).
- `APP_ENV=dev`. Server 1 may not be running — when `JWT_PUBLIC_KEY` is unset, WebSocket auth accepts token `"dev"` (dev bypass by design).
- Postgres + Redis come from `.env` (`DATABASE_URL`, `REDIS_URL`). In this project they are often the **same cloud URLs as Server 1** (shared Supabase Postgres + shared Redis). Server 2 only creates/uses **its own tables** (e.g. `server_health` today); it must **never** write Server 1's user/session/OAuth tables.
- `SERVER1_REDIS_URL`: optional in dev; used only for JWT blocklist keys `blocklist:<jti>`. When shared with Server 1, it can be the same URL as `REDIS_URL`.
- LanceDB: local directory (`LANCEDB_DIR`, default `./data/lancedb`).
- `docker-compose.dev.yml` is **optional** (local Postgres + Redis only). **Do not require Docker.** If `.env` already has working cloud URLs, skip Docker and run the server directly.
- Keep `.env` small: secrets, deployment endpoints, machine-local paths, ports, and explicit overrides only. Put ordinary defaults in `server/config.py` and document optional overrides in `.env.example`.
- Boot: `python -m uvicorn server.app:app --port 8080` (from `Server2/` with venv active). Tests: `python -m pytest tests/unit -q`.

AFTER all acceptance tests pass, do the COMPLETION PHASE — update all tracking files:

1. PLAN.md Section 8: change the status of the completed step from ⬜ to ✅.
2. doc/history.md: add a new entry with today's date, scope, what was built, files created/changed, and which plan sections / diagram pages it relates to. Follow the existing entry template.
3. doc/roadmap.md: update the status emoji of the completed step from ⬜ to ✅.
4. doc/tracker.md: update the build progress grid (change completed step to ✅, update counts). Add/update architecture flow diagrams if this step changes how data moves.
5. If the next step does not have a step file yet (doc/step-<N+1>.md), create it as a stub following the skeleton in PLAN.md Section 12. Set its status to ⬜ pending.
6. Tell me all acceptance tests passed and the tracking files are updated. Then wait for me to say "commit" before making a git commit.

START by reading the files listed above, then tell me which step you are going to implement and present your implementation plan (which files you will create/modify, in what order) before writing any code. Wait for my approval.
