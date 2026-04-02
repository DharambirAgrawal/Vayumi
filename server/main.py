# =============================================================================
# server/main.py — FastAPI Application Entrypoint
# =============================================================================
#
# PURPOSE:
#   The single entry point for the Vayumi server. Creates the FastAPI app,
#   mounts all routers, initializes all shared services on startup, and
#   tears them down on shutdown.
#
# STARTUP RESPONSIBILITIES:
#   1. Initialize SQLite database (WAL mode, create tables if not exist)
#   2. Initialize ChromaDB persistent client
#   3. Load SpeechBrain ECAPA-TDNN model (speaker encoder — ~400MB, cached)
#   4. Load Kokoro-ONNX TTS model
#   5. Load sentence-transformers embedding model (all-MiniLM-L6-v2)
#   6. Load silero-vad model
#   7. Initialize LLMRouter (Groq primary, Gemini fallback)
#   8. Load skill_registry.json and mcp_registry.json
#   9. Create shared service instances accessible by dependency injection
#
# SHUTDOWN RESPONSIBILITIES:
#   1. Close all active WebSocket sessions gracefully
#   2. Close SQLite connection
#   3. Flush any pending memory writes
#
# ROUTES MOUNTED:
#   - WebSocket /ws/vayumi           → server.ws.handler.websocket_endpoint
#   - POST /api/auth/register        → server.auth.router
#   - POST /api/auth/login           → server.auth.router
#   - GET  /api/users/me             → server.auth.router
#   - GET  /api/memory               → (future, user-scoped)
#   - GET  /api/skills               → (future, skill list)
#   - GET  /api/config               → (future, user-scoped config)
#
# CORS:
#   Allow browser client origins (localhost during dev)
#
# RUN:
#   uvicorn server.main:app --host 0.0.0.0 --port 8000
# =============================================================================

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from server.auth.router import auth_router
from server.ws.handler import websocket_endpoint
from server.memory.sqlite_store import SQLiteStore
from server.memory.vector_store import VectorStore
from server.memory.embedder import Embedder
from server.voice.stt import STTEngine
from server.voice.tts import TTSEngine
from server.voice.vad import VADEngine
from server.voice.diarizer import SpeakerIdentifier
from server.llm.router import LLMRouter
from server.skills.skill_runner import SkillRunner
from server.mcps.mcp_runner import MCPRunner


@asynccontextmanager
async def lifespan(app: FastAPI):
    # --- STARTUP ---
    # TODO: Initialize all shared services here:
    #   app.state.sqlite_store = SQLiteStore("data/vayumi.db")
    #   app.state.vector_store = VectorStore("data/vectordb")
    #   app.state.embedder = Embedder()
    #   app.state.stt = STTEngine()
    #   app.state.tts = TTSEngine()
    #   app.state.vad = VADEngine()
    #   app.state.diarizer = SpeakerIdentifier()
    #   app.state.llm_router = LLMRouter()
    #   app.state.skill_runner = SkillRunner()
    #   app.state.mcp_runner = MCPRunner()
    yield
    # --- SHUTDOWN ---
    # TODO: Cleanup all shared services here


app = FastAPI(title="Vayumi", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Restrict in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router, prefix="/api/auth", tags=["auth"])
app.add_api_websocket_route("/ws/vayumi", websocket_endpoint)
