# Vayumi Server 2

Voice-first multi-agent backend (FastAPI + WebSocket).

## What you need

| Piece | What it is | Required? |
|-------|------------|-------------|
| **venv** | Python 3.11 + pip packages | Yes |
| **Postgres** | `DATABASE_URL` — cloud (e.g. Supabase) or any reachable Postgres | Yes |
| **Redis** | `REDIS_URL` — cloud or local Redis | Yes |
| **llama-server** | Local LLM binary + GGUF model under `models/` | Yes |
| **Groq** | `GROQ_API_KEY` for speech-to-text | Yes (default `STT_BACKEND=groq`) |
| **Docker** | Optional — only if you want *local* Postgres/Redis instead of cloud URLs |

The venv does **not** include Postgres or Redis. If `.env` says `localhost:5432` but nothing is listening there, startup fails with `Connection refused`.

## Setup

```bash
python3.11 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
python -m spacy download en_core_web_sm
scrapling install
cp .env.example .env
```

Edit `.env` and set **your** endpoints (typical dev setup without Docker):

```bash
# Cloud Postgres + Redis (same as Server 1 is fine)
DATABASE_URL=postgresql://USER:PASS@YOUR_HOST:5432/postgres
REDIS_URL=redis://...

# Machine-local LLM (Homebrew example)
LLAMA_SERVER_BIN=/opt/homebrew/bin/llama-server

GROQ_API_KEY=your_groq_key
TAVILY_API_KEY=your_tavily_key   # optional; web search falls back to DDG
```

## Run

```bash
source venv/bin/activate
LOG_LEVEL=debug uvicorn server.app:app --port 8080
```

Web client: http://localhost:8080 — WebSocket uses token `dev` when `JWT_PUBLIC_KEY` is unset.

## Optional: local Postgres + Redis via Docker

Only if you prefer localhost instead of cloud URLs there:

```bash
docker compose -f docker-compose.dev.yml up -d
# then in .env:
# DATABASE_URL=postgresql://vayumi:vayumi@localhost:5432/vayumi
# REDIS_URL=redis://localhost:6379/0
```

Deps: `pyproject.toml` / `requirements.txt` (includes `scrapling[fetchers]`, `trafilatura`, `tavily-python`).
