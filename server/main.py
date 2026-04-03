# # =============================================================================
# # server/main.py — FastAPI Application Entrypoint
# # =============================================================================
# #
# # PURPOSE:
# #   The single entry point for the Vayumi server. Creates the FastAPI app,
# #   mounts all routers, initializes all shared services on startup, and
# #   tears them down on shutdown.
# #
# # STARTUP RESPONSIBILITIES:
# #   1. Initialize SQLite database (WAL mode, create tables if not exist)
# #   2. Initialize ChromaDB persistent client
# #   3. Load SpeechBrain ECAPA-TDNN model (speaker encoder — ~400MB, cached)
# #   4. Load Kokoro-ONNX TTS model (server/models/kokoro-v0_19.onnx + server/models/voices.bin)
# #   5. Load sentence-transformers embedding model (all-MiniLM-L6-v2)
# #   6. Load silero-vad model
# #   7. Initialize LLMRouter (Groq primary, Gemini fallback)
# #   8. Load skill_registry.json and mcp_registry.json
# #   9. Create shared service instances accessible by dependency injection
# #
# # SHUTDOWN RESPONSIBILITIES:
# #   1. Close all active WebSocket sessions gracefully
# #   2. Close SQLite connection
# #   3. Flush any pending memory writes
# #
# # ROUTES MOUNTED:
# #   - WebSocket /ws/vayumi           → server.ws.handler.websocket_endpoint
# #   - POST /api/auth/register        → server.auth.router
# #   - POST /api/auth/login           → server.auth.router
# #   - GET  /api/users/me             → server.auth.router
# #   - GET  /api/memory               → (future, user-scoped)
# #   - GET  /api/skills               → (future, skill list)
# #   - GET  /api/config               → (future, user-scoped config)
# #
# # CORS:
# #   Allow browser client origins (localhost during dev)
# #
# # RUN:
# #   uvicorn server.main:app --host 0.0.0.0 --port 8000
# # =============================================================================

# import os
# from contextlib import asynccontextmanager

# from fastapi import FastAPI
# from fastapi.middleware.cors import CORSMiddleware

# from server.auth.router import auth_router
# from server.ws.handler import websocket_endpoint
# from server.memory.sqlite_store import SQLiteStore
# from server.memory.vector_store import VectorStore
# from server.memory.embedder import Embedder
# from server.voice.stt import STTEngine
# from server.voice.tts import TTSEngine
# from server.voice.vad import VADEngine
# from server.voice.diarizer import SpeakerIdentifier
# from server.llm.router import LLMRouter
# from server.skills.skill_runner import SkillRunner
# from server.mcps.mcp_runner import MCPRunner


# @asynccontextmanager
# async def lifespan(app: FastAPI):
#     # --- STARTUP ---
#     # TODO: Initialize all shared services here:
#     #   app.state.sqlite_store = SQLiteStore()  # default: server.paths.DEFAULT_SQLITE_DB
#     #   app.state.vector_store = VectorStore()  # default: server.paths.DEFAULT_VECTORDB_DIR
#     #   app.state.embedder = Embedder()
#     #   app.state.stt = STTEngine()
#     #   app.state.tts = TTSEngine()
#     #   app.state.vad = VADEngine()
#     #   app.state.diarizer = SpeakerIdentifier()
#     #   app.state.llm_router = LLMRouter()
#     #   app.state.skill_runner = SkillRunner()
#     #   app.state.mcp_runner = MCPRunner()
#     yield
#     # --- SHUTDOWN ---
#     # TODO: Cleanup all shared services here


# app = FastAPI(title="Vayumi", version="0.1.0", lifespan=lifespan)

# app.add_middleware(
#     CORSMiddleware,
#     allow_origins=["*"],  # Restrict in production
#     allow_credentials=True,
#     allow_methods=["*"],
#     allow_headers=["*"],
# )

# app.include_router(auth_router, prefix="/api/auth", tags=["auth"])
# app.add_api_websocket_route("/ws/vayumi", websocket_endpoint)


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
#   4. Load Kokoro-ONNX TTS model (server/models/kokoro-v0_19.onnx + server/models/voices.bin)
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
import logging
import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv

# Load server/.env (next to this file) so API keys are available via os.getenv
_env_path = Path(__file__).resolve().parent / ".env"
load_dotenv(_env_path)

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from server.auth.router import auth_router, users_router
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
from server.mcps import register_builtin_handlers

# ---------------------------------------------------------------------------
# Colored log formatter
# ---------------------------------------------------------------------------
class _ColorFormatter(logging.Formatter):
    """ANSI-colored formatter that makes log output easy to scan at a glance."""

    RESET = "\033[0m"
    COLORS = {
        logging.DEBUG:    "\033[36m",   # cyan
        logging.INFO:     "\033[32m",   # green
        logging.WARNING:  "\033[33m",   # yellow
        logging.ERROR:    "\033[31m",   # red
        logging.CRITICAL: "\033[1;31m", # bold red
    }
    LEVEL_TAG = {
        logging.DEBUG:    "DBG",
        logging.INFO:     "INF",
        logging.WARNING:  "WRN",
        logging.ERROR:    "ERR",
        logging.CRITICAL: "CRT",
    }
    # Dim grey for metadata (timestamp / logger name)
    DIM = "\033[90m"
    BOLD = "\033[1m"

    def format(self, record: logging.LogRecord) -> str:
        color = self.COLORS.get(record.levelno, self.RESET)
        tag = self.LEVEL_TAG.get(record.levelno, "???")
        # Shorten the logger name to the last two segments for readability
        name_parts = record.name.rsplit(".", 1)
        short_name = name_parts[-1] if len(name_parts) > 1 else record.name
        ts = self.formatTime(record, "%H:%M:%S")
        msg = record.getMessage()
        base = (
            f"{self.DIM}{ts}{self.RESET} "
            f"{color}{self.BOLD}{tag}{self.RESET} "
            f"{self.DIM}[{short_name}]{self.RESET} "
            f"{color}{msg}{self.RESET}"
        )
        if record.exc_info and not record.exc_text:
            record.exc_text = self.formatException(record.exc_info)
        if record.exc_text:
            base += f"\n{self.COLORS[logging.ERROR]}{record.exc_text}{self.RESET}"
        return base


def _setup_logging() -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(_ColorFormatter())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(logging.INFO)


_setup_logging()
logger = logging.getLogger("vayumi.main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Manages the global startup and shutdown lifecycle of the Vayumi server.
    """
    # ==========================================
    # --- STARTUP ---
    # ==========================================
    logger.info("Initializing Vayumi Server...")

    # Global registry for active WebSocket connections 
    # (websocket_endpoint should add/remove itself from this set)
    app.state.active_websockets = set()

    try:
        # 1. Initialize SQLite database (WAL mode, create tables if not exist)
        app.state.sqlite_store = SQLiteStore()
        
        # 2. Initialize ChromaDB persistent client
        app.state.vector_store = VectorStore()
        
        # 5. Load sentence-transformers embedding model (all-MiniLM-L6-v2)
        app.state.embedder = Embedder()
        
        # STT Engine Initialization
        app.state.stt = STTEngine()
        
        # 4. Load Kokoro-ONNX TTS model
        app.state.tts = TTSEngine()
        
        # 6. Load silero-vad model
        app.state.vad = VADEngine()
        
        # 3. Load SpeechBrain ECAPA-TDNN model (speaker encoder)
        app.state.diarizer = SpeakerIdentifier()
        
        # 7. Initialize LLMRouter (Groq primary, Gemini fallback)
        app.state.llm_router = LLMRouter()
        
        # 8. Load skill_registry.json and mcp_registry.json
        app.state.skill_runner = SkillRunner()
        app.state.mcp_runner = MCPRunner()
        register_builtin_handlers(
            app.state.mcp_runner,
            sqlite_store=app.state.sqlite_store,
        )

        logger.info("All shared services loaded successfully.")
    except Exception as e:
        logger.error(f"Failed during startup initialization: {e}")
        raise

    # Yield control back to FastAPI to start accepting requests
    yield

    # ==========================================
    # --- SHUTDOWN ---
    # ==========================================
    logger.info("Shutting down Vayumi Server...")

    # 1. Close all active WebSocket sessions gracefully
    if hasattr(app.state, "active_websockets"):
        logger.info(f"Closing {len(app.state.active_websockets)} active WebSocket connections...")
        for ws in list(app.state.active_websockets):
            try:
                await ws.close(code=1001, reason="Server shutting down")
            except Exception as e:
                logger.warning(f"Error closing websocket: {e}")
        app.state.active_websockets.clear()

    # Helper function to safely close services whether they are sync or async
    async def safe_close(service, name):
        if hasattr(service, "close"):
            logger.info(f"Closing {name}...")
            try:
                if asyncio.iscoroutinefunction(service.close):
                    await service.close()
                else:
                    service.close()
            except Exception as e:
                logger.error(f"Error closing {name}: {e}")

    # 2. Close SQLite connection & flush memory writes
    await safe_close(app.state.sqlite_store, "SQLite Database")
    
    # 3. Flush any pending memory writes in vector store
    await safe_close(app.state.vector_store, "ChromaDB Vector Store")

    # Gracefully shut down remaining models/services if they require it
    services_to_close = {
        "LLMRouter": app.state.llm_router,
        "STTEngine": app.state.stt,
        "TTSEngine": app.state.tts,
        "SkillRunner": app.state.skill_runner,
        "MCPRunner": app.state.mcp_runner
    }
    for name, service in services_to_close.items():
        await safe_close(service, name)

    logger.info("Vayumi Server shutdown complete.")


# Initialize FastAPI Application
app = FastAPI(title="Vayumi", version="0.1.0", lifespan=lifespan)

# CORS Configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Restrict in production (e.g., ["http://localhost:3000"])
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount Routers
app.include_router(auth_router, prefix="/api/auth", tags=["auth"])
app.include_router(users_router, prefix="/api/users", tags=["users"])

# Mount WebSockets
# (Ensure `websocket_endpoint` uses `app.state.active_websockets.add(websocket)` internally)
app.add_api_websocket_route("/ws/vayumi", websocket_endpoint)

# Browser client: same origin as API so /api/* and /ws/* work without CORS/base-URL tweaks
_client_browser = Path(__file__).resolve().parent.parent / "client" / "browser"
if _client_browser.is_dir():
    app.mount(
        "/",
        StaticFiles(directory=str(_client_browser), html=True),
        name="browser_client",
    )