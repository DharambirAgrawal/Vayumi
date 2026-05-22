from __future__ import annotations

from pathlib import Path

from server.config import Settings
from server.logger import get_logger
from server.voice.stt.groq import GroqWhisper
from server.voice.tts.kokoro import KokoroTTS

log = get_logger("voice.boot")

_SPACY_MODEL = "en_core_web_sm"


def _ensure_spacy_model(*, auto_download: bool) -> None:
    try:
        import spacy
        from spacy.util import is_package
    except Exception as exc:  # pragma: no cover - environment-specific
        raise RuntimeError(
            "spaCy is required for Kokoro TTS. Install with: pip install spacy"
        ) from exc

    if is_package(_SPACY_MODEL):
        return

    if not auto_download:
        raise RuntimeError(
            "spaCy model 'en_core_web_sm' is missing. "
            "Run: python -m spacy download en_core_web_sm"
        )

    log.info("spacy.model_download", model=_SPACY_MODEL)
    spacy.cli.download(_SPACY_MODEL)
    if not is_package(_SPACY_MODEL):
        raise RuntimeError(
            "spaCy model download failed. "
            "Run: python -m spacy download en_core_web_sm"
        )


def validate_voice_settings(settings: Settings) -> None:
    if settings.stt_backend == "groq" and not settings.groq_api_key:
        raise ValueError("GROQ_API_KEY is required when STT_BACKEND=groq")

    model_dir = Path(settings.kokoro_model_dir)
    if not model_dir.exists():
        raise FileNotFoundError(
            f"KOKORO_MODEL_DIR does not exist: {model_dir}. "
            "Create the directory (or place a Kokoro .onnx file there for offline use)."
        )
    from server.voice.tts.kokoro import _resolve_onnx_model_path

    if _resolve_onnx_model_path(model_dir) is None:
        log.warning(
            "kokoro.no_local_onnx",
            model_dir=str(model_dir),
            msg="No .onnx in KOKORO_MODEL_DIR; TTS will download from HuggingFace on first use",
        )

    _ensure_spacy_model(auto_download=settings.is_dev)


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
