from __future__ import annotations

from pathlib import Path

from server.config import Settings
from server.logger import get_logger
from server.voice.stt.groq import GroqWhisper
from server.voice.tts.kokoro import KokoroTTS

log = get_logger("voice.boot")


def validate_voice_settings(settings: Settings) -> None:
    if settings.stt_backend == "groq" and not settings.groq_api_key:
        raise ValueError("GROQ_API_KEY is required when STT_BACKEND=groq")

    model_dir = Path(settings.kokoro_model_dir)
    if not model_dir.exists():
        raise FileNotFoundError(
            f"KOKORO_MODEL_DIR does not exist: {model_dir}. "
            "Download Kokoro ONNX assets into this directory before starting the server."
        )


def create_stt_backend(settings: Settings) -> GroqWhisper:
    if settings.stt_backend != "groq":
        raise ValueError(f"Unsupported STT_BACKEND for step 3: {settings.stt_backend}")
    if not settings.groq_api_key:
        raise ValueError("GROQ_API_KEY is required when STT_BACKEND=groq")
    return GroqWhisper(api_key=settings.groq_api_key)


def create_tts_backend(settings: Settings) -> KokoroTTS:
    return KokoroTTS(
        model_dir=Path(settings.kokoro_model_dir),
        voice=settings.kokoro_voice,
    )


async def init_voice_plane(settings: Settings) -> dict[str, object]:
    validate_voice_settings(settings)
    stt = create_stt_backend(settings)
    tts = create_tts_backend(settings)
    log.info(
        "voice_plane.ready",
        stt_backend=settings.stt_backend,
        kokoro_voice=settings.kokoro_voice,
    )
    return {"stt": stt, "tts": tts}
