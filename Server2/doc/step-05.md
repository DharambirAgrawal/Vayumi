# Step 05 — Memory v1

**Status:** ✅ done  
**Depends on:** step-04  
**Estimated effort:** 2 days  
**Owner:** you  
**Diagram pages:** 09

---

## Goal

Add warm profile, session history, and Postgres versioned facts so Main can remember and recall user information via `[REMEMBER]` and `[RECALL]` directives.

---

## Files this step creates or changes

```
server/db/
├── schema.sql                   NEW — facts, sessions, turns
├── postgres.py                  CHANGED — run schema.sql on boot
└── lancedb.py                   CHANGED — facts_index table
server/memory/
├── __init__.py                  NEW
├── embeddings.py                NEW — bge-small embedder (sentence-transformers)
├── facts.py                     NEW — versioned fact CRUD + LanceDB upsert
├── warm.py                      NEW — warm profile + dirty flag + Redis cache
├── session.py                   NEW — session rows + turn history
└── retrieval.py                 NEW — stub (full semantic search in step 11)
server/orchestrator/
├── __init__.py                  NEW
├── directives.py                NEW — REMEMBER / RECALL parsing + execution
└── supervisor.py                NEW — context assembly + turn lifecycle
server/engine/prompt.py          CHANGED — warm + history blocks
server/transport/ws.py           CHANGED — route chat through supervisor
server/voice/turn.py             CHANGED — route voice through supervisor
server/app.py                    CHANGED — schema + embedder init
server/config.py                 CHANGED — bge_model_path
prompts/main.txt                 CHANGED — memory directives
pyproject.toml                   CHANGED — sentence-transformers
.env.example                     CHANGED — BGE_MODEL_PATH
tests/unit/
├── test_memory_facts.py         NEW
├── test_memory_warm.py          NEW
├── test_memory_session.py       NEW
├── test_directives.py           NEW
├── test_supervisor.py           NEW
└── test_engine_prompt.py        CHANGED
```

---

## Detailed tasks

### 1. Schema (`server/db/schema.sql`)

- `facts`: versioned rows per diagram (UUID id, user_id, key, value JSONB, active, source, confidence, created_at, superseded_at, superseded_by).
- Partial unique index: one active row per `(user_id, key)`.
- `sessions`: id, user_id, client_meta JSONB, created_at, last_seen_at, compressed_summary TEXT nullable.
- `turns`: id, session_id, user_id, role, text, created_at.
- Idempotent `CREATE TABLE IF NOT EXISTS` only.

### 2. Embeddings (`server/memory/embeddings.py`)

- `init_embedder()` at boot via `sentence-transformers` (`BAAI/bge-small-en-v1.5`, 384-dim).
- `embed_text(text) -> list[float]`.
- `BGE_MODEL_PATH` documented in `.env.example`; encoder loads by model name (ONNX path reserved for later export).

### 3. Facts (`server/memory/facts.py`)

- `set_fact(user_id, key, value, source, confidence=1.0)` — supersede active row, insert new, embed + upsert LanceDB `facts_index`, `mark_dirty` when key affects warm profile.
- `get_fact(user_id, key)` — active value.
- `get_chain(user_id, key)` — ordered chain newest-first.

### 4. Warm (`server/memory/warm.py`)

- `WARM_KEY_PREFIXES` — profile keys (name, city, email.*, comm_style.*, relationships.*, integrations.*).
- `build_warm_profile(user_id)` — ~600 token budget, Redis cache `warm_cache:<user_id>` TTL 10m.
- `mark_dirty(user_id)` — invalidate cache.

### 5. Session (`server/memory/session.py`)

- `load_or_create_session(user_id, session_id, client_meta)`.
- `append_turn(session_id, user_id, role, text)`.
- `recent_turns(session_id, limit=8)`.
- `compressed_history(session_id)` — returns stored summary or empty.

### 6. Retrieval stub (`server/memory/retrieval.py`)

- `retrieve(query, filters, k)` raises `NotImplementedError` (step 11).

### 7. Directives (`server/orchestrator/directives.py`)

- Parse `[REMEMBER key=… value=… source="…"]`, `[RECALL key=…]`, `[RECALL chain key=…]`.
- `execute_directives(user_id, directives) -> list[RecallResult]`.
- `strip_directives(text) -> str` for captions/TTS.

### 8. Supervisor (`server/orchestrator/supervisor.py`)

- `Supervisor(user_id, session_id)` — one instance per `user_id` (session singleton, PLAN.md §5.0). WebSocket reattaches via `attach_transport()`; not one Supervisor per socket.
- `run_turn(user_text, engine_pool, on_token)` — warm + history + completion; post-process directives; optional follow-up completion when RECALL needs injection; persist user + assistant turns.

### 9. Integration

- `ws._handle_chat` and `voice/turn.run_voice_turn` call `Supervisor.run_turn`.
- Update `prompts/main.txt` with REMEMBER/RECALL grammar.

### 10. Tests

- Facts versioning with mocked asyncpg pool.
- Directive parse/execute unit tests.
- Prompt includes warm/history when provided.
- Supervisor follow-up on RECALL (mocked engine).

---

## Acceptance test

Run in order. All must pass unless marked optional.

1. `python -m pytest tests/unit -q` — green with venv active.
2. `ruff check server/ tests/` — all checks passed.
3. `python -m uvicorn server.app:app --port 8080` boots cleanly (Postgres, Redis, LanceDB, embedder init).
4. Unit: `set_fact` supersedes prior active row; `get_chain` returns active + superseded in order.
5. Unit: `mark_dirty` then `build_warm_profile` includes updated fact.
6. Unit: REMEMBER/RECALL directives parsed and executed (mocked DB).
7. Web client still loads; connect token `dev` → voice + typed chat still stream captions (step 4 behaviors).
8. Optional live: typed chat with REMEMBER/RECALL depends on local model following `prompts/main.txt`.

If all pass, mark Step 5 ✅ in tracking files and stub `doc/step-06.md` if missing.

---

## Out of scope

- Tool plane, sub-agents, signal bus, task board
- Full LanceDB semantic `retrieve()` (step 11)
- Summarizer P2, `[DELEGATE]`, mid-stream directive pause (post-stream + follow-up only in this step)
- File upload, MCP

---

## Risks and how we'll catch them

- Shared Postgres — Server 2-only table names; idempotent DDL.
- Embedder download on first boot — log clearly; unit tests mock `embed_text`.
- Directive strip leaves empty TTS — if only directives in output, follow-up completion supplies user-visible text.

---

## Notes for the next step

Step 6 backfills the v1.7 contracts (session singleton, respond_via, echo suppression, chat_message).
