# =============================================================================
# server/paths.py — Resolved paths under the server package
# =============================================================================
#
# All persistent server-local storage lives under this package directory:
#   server/data/   — SQLite, ChromaDB
#   server/models/ — Local ML assets: Kokoro TTS (onnx + voices.bin), SpeechBrain cache, etc.
#
# Paths are resolved from Path(__file__), not the process cwd, so uvicorn can be
# started from the repo root or elsewhere without breaking file locations.
# =============================================================================

from pathlib import Path

SERVER_ROOT = Path(__file__).resolve().parent

DATA_DIR = SERVER_ROOT / "data"
MODELS_DIR = SERVER_ROOT / "models"

DEFAULT_SQLITE_DB = DATA_DIR / "vayumi.db"
DEFAULT_VECTORDB_DIR = DATA_DIR / "vectordb"

DEFAULT_KOKORO_ONNX = MODELS_DIR / "kokoro-v0_19.onnx"
DEFAULT_KOKORO_VOICES = MODELS_DIR / "voices.bin"
DEFAULT_SPEAKER_ENCODER_CACHE = MODELS_DIR / "speaker_encoder"
