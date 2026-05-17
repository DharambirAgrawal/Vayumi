# History

This log tracks updates pushed to GitHub for Server2. Each entry should be small, factual, and tied to the plan and diagram when relevant.

## How to log

- One entry per push or merged PR.
- Keep the title short and specific.
- Include verification steps or note N/A.
- Reference plan sections or diagram pages when the change aligns with them.

## Entry template

## YYYY-MM-DD - Short title

**Scope:** docs | infra | transport | voice | engine | orchestrator | tools | memory | client | tests

**Why:** One sentence on the problem or goal.

**Key changes:**
- Change 1
- Change 2

**Files/areas:**
- Path or module area

**Plan/diagram references:**
- PLAN section(s) or diagram page(s)

**Tests/verification:**
- Command(s) run or N/A

**Follow-ups:**
- Next steps, if any

---

## 2026-05-11 - History log created

**Scope:** docs

**Why:** Establish a consistent place to track updates pushed to GitHub.

**Key changes:**
- Added this history log and template.

**Files/areas:**
- doc/history.md

**Plan/diagram references:**
- [PLAN.md](../PLAN.md) v1.4 (2026-05-10)
- [orchestrator_diagram_v3.drawio](../orchestrator_diagram_v3.drawio) (17 pages)
- [doc/step-01.md](step-01.md) (pending)

**Tests/verification:**
- N/A

**Follow-ups:**
- Add an entry for each push or merged PR going forward.

---

## 2026-05-17 - Step 1 complete: Project scaffold + WebSocket echo

**Scope:** infra | transport | client | tests

**Why:** Stand up the server spine — FastAPI, database wiring, auth, WebSocket echo, and a working web client — so every later step plugs into a verified foundation.

**Key changes:**
- FastAPI app with lifespan boot sequence (Postgres → Redis → LanceDB → server_health)
- Pydantic Settings with fail-fast validation; cloud Postgres + Redis (shared infra with Server 1)
- `verify_token()` with RS256 prod path and clean dev bypass (token="dev" when no JWT_PUBLIC_KEY)
- WebSocket endpoint `/ws/v1/session` with echo behavior (JSON + binary PCM)
- Typed Pydantic protocol models (Hello, Chat, AudioStart, AudioEnd, Ping / Welcome, Echo, Pong, Error)
- Reference web client: vanilla JS, AudioWorklet PCM capture, WS connect/send/receive
- structlog logging (JSON prod, pretty dev)
- 17 unit tests for protocol round-trips — all green
- Replaced `implementation_tracker.drawio` with `doc/tracker.md` (markdown progress grid + ASCII architecture flow diagrams)

**Files/areas:**
- NEW: `pyproject.toml`, `.env.example`, `.gitignore`, `docker-compose.dev.yml`
- NEW: `server/{__init__,app,config,logger,auth}.py`
- NEW: `server/db/{__init__,postgres,redis,lancedb}.py`
- NEW: `server/transport/{__init__,ws,protocol}.py`
- NEW: `web-client/{index.html,client.js}`
- NEW: `tests/{__init__,conftest}.py`, `tests/unit/test_protocol.py`
- NEW: `doc/tracker.md`
- DELETED: `implementation_tracker.drawio`
- CHANGED: `PLAN.md` (step 1 ⬜→✅, tracker reference updated)
- CHANGED: `doc/roadmap.md` (step 1 ⬜→✅, tracker reference updated)
- CHANGED: `agent-prompt.md` (tracker reference updated)

**Plan/diagram references:**
- PLAN.md §2 (stack), §4 (folder structure), §5 (WS protocol), §10 (env vars), §11 (deps)
- Diagram pages 01 (system overview), 02 (transport), 03 (auth), 14 (boot sequence)

**Tests/verification:**
- `ruff check server/ tests/` — all checks passed
- `pytest tests/unit -q` — 17 passed
- Server boots cleanly against cloud Postgres + Redis: "postgres ok / redis ok / lancedb ok / dev mode: auth bypass enabled / app.ready"
- Web client loads at `http://localhost:8080`

**Follow-ups:**
- Step 2: Engine plane (llama-server runner + slot pool + main-only completion)
