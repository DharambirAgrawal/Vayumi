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

def _first_existing(*candidates: Path) -> Path:
	for p in candidates:
		if p.exists():
			return p
	return candidates[0]


DEFAULT_KOKORO_ONNX = _first_existing(
	MODELS_DIR / "kokoro-v1.0.onnx",
	MODELS_DIR / "kokoro-v0_19.onnx",
)
DEFAULT_KOKORO_VOICES = _first_existing(
	MODELS_DIR / "voices-v1.0.bin",
	MODELS_DIR / "voices.bin",
)
DEFAULT_SPEAKER_ENCODER_CACHE = MODELS_DIR / "speaker_encoder"
