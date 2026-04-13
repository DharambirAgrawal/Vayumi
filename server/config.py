"""Runtime settings for the Vayumi server."""

from dataclasses import dataclass
import os
from pathlib import Path


def _load_env_file(path: Path) -> None:
    if not path.exists() or not path.is_file():
        return

    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue

        key, value = stripped.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def _bootstrap_env() -> None:
    server_dir = Path(__file__).resolve().parent
    candidates = [
        server_dir / ".env",
        server_dir.parent / ".env",
        server_dir.parent.parent / ".env",
    ]

    for env_path in candidates:
        _load_env_file(env_path)


_bootstrap_env()


def _get_env(name: str, default: str) -> str:
    value = os.getenv(name)
    if value is None:
        return default
    return value.split("#", 1)[0].strip() or default


def _get_int_env(name: str, default: int) -> int:
    try:
        return int(_get_env(name, str(default)))
    except ValueError:
        return default


def _get_float_env(name: str, default: float) -> float:
    try:
        return float(_get_env(name, str(default)))
    except ValueError:
        return default


def _get_bool_env(name: str, default: bool) -> bool:
    value = _get_env(name, "true" if default else "false").lower()
    return value in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class ServerSettings:
    host: str = _get_env("HOST", "0.0.0.0")
    port: int = _get_int_env("PORT", 8000)
    session_timeout_seconds: int = _get_int_env("SESSION_TIMEOUT_SECONDS", 60)
    stt_provider: str = _get_env("STT_PROVIDER", "whisper")
    stt_model: str = _get_env("STT_MODEL", "whisper-large-v3")
    stt_language: str = _get_env("STT_LANGUAGE", "en")
    tts_provider: str = _get_env("TTS_PROVIDER", "kokoro_onnx")
    tts_voice: str = _get_env("KOKORO_VOICE", "af_heart")
    tts_fallback_voice: str = _get_env("TTS_FALLBACK_VOICE", "Samantha")
    tts_allow_system_fallback: bool = _get_bool_env("TTS_ALLOW_SYSTEM_FALLBACK", False)
    kokoro_model_path: str = _get_env(
        "KOKORO_MODEL_PATH",
        str(Path(__file__).resolve().parents[2] / "models" / "kokoro-v1.0.onnx"),
    )
    kokoro_voices_path: str = _get_env(
        "KOKORO_VOICES_PATH",
        str(Path(__file__).resolve().parents[2] / "models" / "voices-v1.0.bin"),
    )
    kokoro_speed: float = _get_float_env("KOKORO_SPEED", 1.0)
    stt_prompt: str = _get_env(
        "STT_PROMPT",
        "Wake word is Vayumi. Possible spellings: Vayumi, Wayumi, Vai Umi, Vaiyumi.",
    )
    stt_request_timeout_seconds: float = _get_float_env("STT_REQUEST_TIMEOUT_SECONDS", 30.0)
    vad_silence_duration_ms: int = _get_int_env("VAD_SILENCE_DURATION_MS", 320)
    vad_rms_threshold: float = _get_float_env("VAD_RMS_THRESHOLD", 0.05)
    min_transcribe_segment_ms: int = _get_int_env("MIN_TRANSCRIBE_SEGMENT_MS", 1200)
    meeting_min_transcribe_segment_ms: int = _get_int_env("MEETING_MIN_TRANSCRIBE_SEGMENT_MS", 6000)
    agent_chunk_delay_ms: int = _get_int_env("AGENT_CHUNK_DELAY_MS", 20)
    wake_command_window_seconds: int = _get_int_env("WAKE_COMMAND_WINDOW_SECONDS", 8)
    wake_single_command_mode: bool = _get_bool_env("WAKE_SINGLE_COMMAND_MODE", True)
    min_command_gap_seconds: float = _get_float_env("MIN_COMMAND_GAP_SECONDS", 1.2)
    self_echo_suppression_seconds: float = _get_float_env("SELF_ECHO_SUPPRESSION_SECONDS", 2.0)
    wake_interrupt_min_confidence: float = _get_float_env("WAKE_INTERRUPT_MIN_CONFIDENCE", 0.78)
    live_interrupt_check_ms: int = _get_int_env("LIVE_INTERRUPT_CHECK_MS", 400)
    live_interrupt_buffer_ms: int = _get_int_env("LIVE_INTERRUPT_BUFFER_MS", 900)
    wake_detector_provider: str = _get_env("WAKE_DETECTOR_PROVIDER", "local_whisper")
    wake_detector_threshold: float = _get_float_env("WAKE_DETECTOR_THRESHOLD", 0.45)
    wake_detector_model_path: str = _get_env("WAKE_DETECTOR_MODEL_PATH", "")
    wake_word_name: str = _get_env("WAKE_WORD_NAME", "vayumi")
    wake_detector_whisper_model: str = _get_env("WAKE_DETECTOR_WHISPER_MODEL", "tiny.en")
    wake_detector_whisper_language: str = _get_env("WAKE_DETECTOR_WHISPER_LANGUAGE", "en")
    groq_api_key: str = _get_env("GROQ_API_KEY", "")
    groq_base_url: str = _get_env("GROQ_BASE_URL", "https://api.groq.com/openai/v1")
    owner_voice_threshold: float = _get_float_env("OWNER_VOICE_THRESHOLD", 0.75)
    diarization_provider: str = _get_env("DIARIZATION_PROVIDER", "pyannote")
    agent_model: str = _get_env("AGENT_MODEL", "gpt-3.5-turbo")
    database_url: str = _get_env("DATABASE_URL", _get_env("NEON_API_KEY", ""))
    jwt_secret: str = _get_env("JWT_SECRET", "change_me_for_prod")
    jwt_algorithm: str = _get_env("JWT_ALGORITHM", "HS256")
    jwt_ttl_seconds: int = _get_int_env("JWT_TTL_SECONDS", 604800)


settings = ServerSettings()