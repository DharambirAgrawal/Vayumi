"""FastAPI application with WebSocket endpoints."""

from __future__ import annotations

import asyncio
import base64
import inspect
import json
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from typing import Dict, Optional
import uuid
import re
import unicodedata
from pathlib import Path
import urllib.request
import jwt

from fastapi import Depends, FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field
from starlette.websockets import WebSocketState

from agent.runner import AgentRunner
from auth import AuthService, UserRecord
from audio.pipeline import AudioPipeline
from config import settings
from models import ClientType, Mode, ResumePolicy, AudioConfig, TranscriptionSegment, DiarizationSegment
from diarization.engine import DiarizationEngine
from session.manager import SessionManager
from speaker import SpeakerRecognitionEngine
from stt.engine import STTEngine, TranscriptionResult
from tts.engine import TTSEngine
from wake_word import WakeWordDetector
from runtime_constants import DEFAULT_WAKE_COMMAND_WINDOW_SECONDS, InterruptPolicy, RespondVia, WsEvent
from agent.tools.external import analyze_image as external_analyze_image
from agent.tools.external import analyze_video as external_analyze_video
from agent.tools.external import read_url as external_read_url
from agent.tools.external import transcribe_audio as external_transcribe_audio

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

WAKE_WORD_PATTERNS = [
    "vayumi",
    "wayumi",
    "vaiyumi",
    "vai umi",
    "vai, umi",
]


session_manager: Optional[SessionManager] = None
audio_pipeline: Optional[AudioPipeline] = None
speaker_engine: Optional[SpeakerRecognitionEngine] = None
agent_runner: Optional[AgentRunner] = None
auth_service: Optional[AuthService] = None
tts_engine: Optional[TTSEngine] = None
wake_word_detector: Optional[WakeWordDetector] = None
diarization_engine: Optional[DiarizationEngine] = None
active_websockets: Dict[str, WebSocket] = {}
active_response_tasks: Dict[str, asyncio.Task] = {}
session_owner_map: Dict[str, str] = {}
live_wake_interrupt_buffers: Dict[str, bytearray] = {}
live_wake_interrupt_checked_bytes: Dict[str, int] = {}
meeting_audio_accumulators: Dict[str, bytearray] = {}

bearer_scheme = HTTPBearer(auto_error=False)


class ChatRequest(BaseModel):
    text: str
    respond_via: str = RespondVia.CHAT_ONLY
    session_id: Optional[str] = None
    interrupt_policy: str = InterruptPolicy.QUEUE
    attachments: list[dict] = Field(default_factory=list)


class ChatResponsePayload(BaseModel):
    response_id: str
    text: str
    spoken: bool
    routed_via: str
    session_id: Optional[str] = None


class RegisterRequest(BaseModel):
    email: str
    password: str
    name: Optional[str] = None


class LoginRequest(BaseModel):
    email: str
    password: str


class ResumePolicyRequest(BaseModel):
    policy: str


class SpeakRequest(BaseModel):
    text: str
    respond_via: str = RespondVia.VOICE_AND_CHAT


def _record_session_attachments(session, attachments: list[dict] | None) -> None:
    if not attachments:
        return
    if not hasattr(session, "attachments"):
        session.attachments = []
    session.attachments.extend(dict(item) for item in attachments if isinstance(item, dict))


def _attachment_label(attachment: dict) -> str:
    attachment_type = str(attachment.get("type") or attachment.get("mime_type") or "attachment").lower()
    title = attachment.get("title") or attachment.get("name") or attachment.get("filename")
    url = attachment.get("url") or attachment.get("href")
    label = title or url or attachment_type or "attachment"
    return f"{attachment_type}:{label}"


def _decode_attachment_bytes(attachment: dict) -> bytes | None:
    candidates = [attachment.get("data"), attachment.get("content"), attachment.get("base64"), attachment.get("bytes")]
    for value in candidates:
        if isinstance(value, bytes):
            return value
        if isinstance(value, str) and value.strip():
            raw = value.strip()
            if raw.startswith("data:") and "," in raw:
                raw = raw.split(",", 1)[1]
            try:
                return base64.b64decode(raw, validate=True)
            except Exception:
                if str(attachment.get("mime_type", "")).startswith("text/"):
                    return raw.encode("utf-8", errors="ignore")

    path_value = attachment.get("path") or attachment.get("file_path")
    if path_value:
        path = Path(str(path_value))
        if path.exists():
            return path.read_bytes()

    return None


async def _download_attachment_bytes(url: str) -> bytes | None:
    try:
        request = urllib.request.Request(str(url), headers={"User-Agent": "Vayumi/1.0"})
        with urllib.request.urlopen(request, timeout=12) as response:
            return response.read(8_000_000)
    except Exception:
        return None


async def _maybe_await(value):
    if inspect.isawaitable(value):
        return await value
    return value


def _render_tool_result(result: object) -> str:
    if result is None:
        return ""

    if isinstance(result, str):
        text = result.strip()
        if not text:
            return ""
        try:
            payload = json.loads(text)
            if isinstance(payload, dict):
                for key in ("summary", "transcript", "reason", "clean_text"):
                    value = payload.get(key)
                    if isinstance(value, str) and value.strip():
                        return value.strip()
                return json.dumps(payload, ensure_ascii=False)
        except Exception:
            return text

    return str(result)


async def _describe_attachment(attachment: dict) -> str:
    attachment_type = str(attachment.get("type") or attachment.get("mime_type") or "").lower()
    url = attachment.get("url") or attachment.get("href")
    label = _attachment_label(attachment)
    data = _decode_attachment_bytes(attachment)

    if attachment_type == "link" or (url and not attachment_type.startswith(("image", "audio", "video"))):
        if url:
            summary = await _maybe_await(external_read_url(str(url)))
            rendered = _render_tool_result(summary)
            if rendered:
                return f"[{label}] {rendered}"
            return f"[{label}] {url}"

    if attachment_type.startswith("image"):
        if data is None and url and attachment.get("download", True):
            data = await _download_attachment_bytes(str(url))
        if data is None:
            return f"[{label}] image attachment received but no bytes were provided"
        summary = await _maybe_await(external_analyze_image(data))
        rendered = _render_tool_result(summary)
        return f"[{label}] {rendered or 'image analysis unavailable'}"

    if attachment_type.startswith("audio"):
        if data is None and url and attachment.get("download", True):
            data = await _download_attachment_bytes(str(url))
        if data is None:
            return f"[{label}] audio attachment received but no bytes were provided"
        summary = await _maybe_await(external_transcribe_audio(data))
        rendered = _render_tool_result(summary)
        return f"[{label}] {rendered or 'audio transcription unavailable'}"

    if attachment_type.startswith("video"):
        if data is None and url and attachment.get("download", True):
            data = await _download_attachment_bytes(str(url))
        if data is None:
            return f"[{label}] video attachment received but no bytes were provided"
        summary = await _maybe_await(external_analyze_video(data))
        rendered = _render_tool_result(summary)
        return f"[{label}] {rendered or 'video analysis unavailable'}"

    if data is not None:
        if str(attachment.get("mime_type", "")).startswith("text/"):
            text = data.decode("utf-8", errors="ignore").strip()
            return f"[{label}] {text[:2000]}"
        return f"[{label}] received {len(data)} bytes"

    return f"[{label}] attachment received"


async def _build_attachment_context(attachments: list[dict] | None) -> str:
    if not attachments:
        return ""

    rendered: list[str] = []
    for attachment in attachments:
        if not isinstance(attachment, dict):
            continue
        try:
            rendered.append(await _describe_attachment(attachment))
        except Exception as exc:
            rendered.append(f"[attachment] analysis failed: {exc}")

    if not rendered:
        return ""

    return "[ATTACHMENTS]\n" + "\n\n".join(rendered)


async def _compose_transcript_with_attachments(transcript: str, attachments: list[dict] | None) -> str:
    attachment_context = await _build_attachment_context(attachments)
    if not attachment_context:
        return transcript

    return f"{transcript}\n\n{attachment_context}"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI lifespan context manager."""

    global session_manager, audio_pipeline, speaker_engine, agent_runner, auth_service, tts_engine, wake_word_detector, diarization_engine

    logger.info("Starting Vayumi server...")
    session_manager = SessionManager(session_timeout_seconds=settings.session_timeout_seconds)
    stt_engine = STTEngine.from_env(
        provider=settings.stt_provider,
        model=settings.stt_model,
        base_url=settings.groq_base_url,
        prompt=settings.stt_prompt,
        language=settings.stt_language,
        request_timeout_seconds=settings.stt_request_timeout_seconds,
    )
    speaker_engine = SpeakerRecognitionEngine(match_threshold=settings.owner_voice_threshold)
    audio_pipeline = AudioPipeline(
        sample_rate=16000,
        stt_engine=stt_engine,
        speaker_engine=speaker_engine,
        silence_duration_ms=settings.vad_silence_duration_ms,
        vad_threshold=settings.vad_rms_threshold,
    )
    agent_runner = AgentRunner(model=settings.agent_model)
    tts_engine = TTSEngine(
        provider=settings.tts_provider,
        sample_rate=16000,
        voice=settings.tts_voice,
        fallback_voice=settings.tts_fallback_voice,
        allow_system_fallback=settings.tts_allow_system_fallback,
        model_path=settings.kokoro_model_path,
        voices_path=settings.kokoro_voices_path,
        speed=settings.kokoro_speed,
    )
    wake_word_detector = WakeWordDetector(
        provider=settings.wake_detector_provider,
        threshold=settings.wake_detector_threshold,
        model_path=settings.wake_detector_model_path,
        wake_word_name=settings.wake_word_name,
        whisper_model_name=settings.wake_detector_whisper_model,
        whisper_language=settings.wake_detector_whisper_language,
    )
    diarization_engine = DiarizationEngine(provider=settings.diarization_provider)
    if not settings.database_url:
        raise RuntimeError("DATABASE_URL (or NEON_API_KEY) is required for authentication")
    auth_service = AuthService(
        database_url=settings.database_url,
        jwt_secret=settings.jwt_secret,
        jwt_algorithm=settings.jwt_algorithm,
        token_ttl_seconds=settings.jwt_ttl_seconds,
    )
    await auth_service.connect()

    async def cleanup_task():
        while True:
            await asyncio.sleep(30)
            await session_manager.cleanup_expired_sessions()

    cleanup_handle = asyncio.create_task(cleanup_task())

    yield

    logger.info("Shutting down Vayumi server...")
    cleanup_handle.cancel()
    try:
        await cleanup_handle
    except asyncio.CancelledError:
        pass
    await stt_engine.close()
    if auth_service is not None:
        await auth_service.close()


app = FastAPI(
    title="Vayumi AI Agent Platform",
    description="Real-time voice interaction platform",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


async def _send_json(websocket: WebSocket, data: dict) -> bool:
    if websocket.client_state != WebSocketState.CONNECTED:
        return False

    try:
        await websocket.send_json(data)
        return True
    except RuntimeError as exc:
        # A background task can race with socket teardown; treat it as a normal disconnect path.
        if "Unexpected ASGI message 'websocket.send'" in str(exc):
            logger.debug("Dropped send on closed websocket")
            return False
        logger.error("Error sending JSON: %s", exc)
        return False
    except Exception as exc:
        logger.error("Error sending JSON: %s", exc)
        return False


async def _send_error(websocket: WebSocket, code: str, message: str, fatal: bool = False) -> None:
    await _send_json(
        websocket,
        {
            "type": WsEvent.ERROR,
            "code": code,
            "message": message,
            "fatal": fatal,
        },
    )


async def _get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
) -> UserRecord:
    if credentials is None or not credentials.credentials:
        raise HTTPException(status_code=401, detail="Missing bearer token")

    if auth_service is None:
        raise HTTPException(status_code=503, detail="Auth service unavailable")

    try:
        payload = auth_service.decode_access_token(credentials.credentials)
        user_id = payload.get("sub")
        if not user_id:
            raise HTTPException(status_code=401, detail="Invalid token")
        user = await auth_service.get_user_by_id(user_id)
        if user is None:
            raise HTTPException(status_code=401, detail="User not found")
        return user
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")


def _extract_bearer_token_from_ws(websocket: WebSocket) -> Optional[str]:
    auth_header = websocket.headers.get("authorization", "")
    if auth_header.lower().startswith("bearer "):
        return auth_header.split(" ", 1)[1].strip()

    qp_token = websocket.query_params.get("token")
    if qp_token:
        return qp_token
    return None


async def _require_ws_user(websocket: WebSocket) -> UserRecord:
    if auth_service is None:
        raise HTTPException(status_code=503, detail="Auth service unavailable")

    token = _extract_bearer_token_from_ws(websocket)
    if not token:
        raise HTTPException(status_code=401, detail="Missing websocket auth token")

    try:
        payload = auth_service.decode_access_token(token)
        user_id = payload.get("sub")
        if not user_id:
            raise HTTPException(status_code=401, detail="Invalid websocket token")
        user = await auth_service.get_user_by_id(user_id)
        if user is None:
            raise HTTPException(status_code=401, detail="User not found")
        return user
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid websocket token")


def _normalize_text(text: str) -> str:
    lowered = text.lower().strip()
    lowered = unicodedata.normalize("NFKD", lowered)
    lowered = "".join(ch for ch in lowered if not unicodedata.combining(ch))
    lowered = re.sub(r"\s+", " ", lowered)
    return lowered


def _strip_wake_word(text: str) -> tuple[bool, str]:
    normalized = _normalize_text(text)
    collapsed = re.sub(r"[^\w\s\u0400-\u04FF]", " ", normalized)
    collapsed = re.sub(r"\s+", " ", collapsed).strip()

    for pattern in WAKE_WORD_PATTERNS:
        normalized_pattern = re.sub(r"\s+", " ", _normalize_text(pattern)).strip()
        if not normalized_pattern:
            continue

        idx = collapsed.find(normalized_pattern)
        if idx == -1:
            continue

        # Remove the first wake-word occurrence from the original transcript.
        wake_regex = re.compile(re.escape(pattern), flags=re.IGNORECASE)
        cleaned = wake_regex.sub("", text, count=1).strip(" ,.!?;:-")
        return True, cleaned.strip()

    return False, text.strip()


def _open_wake_window(session, seconds: Optional[int] = None) -> None:
    duration = seconds if seconds is not None else getattr(session, "wake_window_seconds", DEFAULT_WAKE_COMMAND_WINDOW_SECONDS)
    session.open_wake_window(duration)


def _close_wake_window(session) -> None:
    session.close_wake_window()


async def _expire_wake_window_if_needed(websocket: WebSocket, session) -> None:
    if session.wake_window_expires_at is None:
        return

    if datetime.utcnow() > session.wake_window_expires_at:
        _close_wake_window(session)
        await _send_json(
            websocket,
            {
                "type": WsEvent.WAKE_WINDOW_CLOSED,
            },
        )
        await _send_json(
            websocket,
            {
                "type": WsEvent.WAKE_WORD_STATUS,
                "status": "sleeping",
            },
        )


async def _handle_wake_trigger(
    websocket: WebSocket,
    session,
    source: str = "server_transcript",
    confidence: float = 0.9,
) -> None:
    _open_wake_window(session, settings.wake_command_window_seconds)
    session.wake_word_active = True
    await _send_json(
        websocket,
        {
            "type": WsEvent.WAKE_WORD_STATUS,
            "status": "command-window-open",
        },
    )
    await _send_json(
        websocket,
        {
            "type": WsEvent.WAKE_WORD_DETECTED,
            "source": source,
            "confidence": confidence,
        },
    )
    await _send_json(
        websocket,
        {
            "type": WsEvent.WAKE_WINDOW_OPENED,
            "window_seconds": settings.wake_command_window_seconds,
        },
    )


async def _interrupt_active_response(websocket: WebSocket, session, trigger: str = "wake_word") -> None:
    if not session.is_ai_speaking and not session.current_response_id:
        return

    session.interrupted = True
    resume_words = _build_resume_words(session)
    session.pending_resume_words = resume_words
    session.pending_resume_response_id = session.current_response_id
    session.response_generation += 1
    response_task = active_response_tasks.get(session.session_id)
    if response_task and not response_task.done():
        response_task.cancel()
        try:
            await asyncio.wait_for(response_task, timeout=0.25)
        except (asyncio.CancelledError, asyncio.TimeoutError):
            pass
    if agent_runner is not None:
        await agent_runner.cancel(session.session_id)
    if audio_pipeline is not None:
        await audio_pipeline.reset_session(session.session_id)
    if tts_engine is not None:
        await tts_engine.cancel(session.session_id)
    session.tts_state.active = False
    session.tts_state.response_id = None
    live_wake_interrupt_buffers.pop(session.session_id, None)
    live_wake_interrupt_checked_bytes.pop(session.session_id, None)

    await _send_json(
        websocket,
        {
            "type": WsEvent.INTERRUPT_ACK,
            "flushed_response_id": session.current_response_id,
            "queued_chars_dropped": 0,
            "trigger": trigger,
            "resume_policy": session.resume_policy.value,
            "resumable_tokens": len(resume_words),
        },
    )

    session.is_ai_speaking = False
    session.current_response_id = None


def _build_demo_response_text(transcript: str, fallback_text: str) -> str:
    transcript = transcript.strip()
    if not transcript:
        return fallback_text

    normalized = transcript.lower()
    if any(keyword in normalized for keyword in ["long", "interrupt test", "speak longer", "tell me something long"]):
        return (
            f"Understood. You asked for a longer response based on: {transcript}. "
            "I will keep speaking for a bit so you can test interruption timing. "
            "This sentence is intentionally longer and paced so you can cut in at different points. "
            "If you interrupt now, the system should pause this response and wait for the next command. "
            "Continuing a little more to make the timing window clear. "
            "This is the final sentence of the long test response."
        )

    demo_templates = [
        f"Understood. I heard: {transcript}. I am handling that now. If you interrupt now, the system should pause this response and wait for the next command.",
        f"Okay. Your command was: {transcript}. I can keep going or stop if you interrupt me. If you interrupt now, the system should pause this response and wait for the next command.",
        f"Confirmed. I received: {transcript}. Awaiting the next command. If you interrupt now, the system should pause this response and wait for the next command.",
    ]
    index = abs(hash(transcript)) % len(demo_templates)
    return demo_templates[index]


def _build_resume_words(session) -> list[str]:
    words = session.current_response_words or []
    idx = session.current_response_word_index
    checkpoint = session.current_response_checkpoint_index
    if not words:
        return []

    # If interruption lands during TTS after text chunks are complete,
    # keep the response resumable from a meaningful checkpoint.
    if idx >= len(words):
        if session.tts_state.active:
            idx = max(0, len(words) - 1)
        else:
            return []

    if session.resume_policy == ResumePolicy.CONTINUE_TOKEN_STREAM:
        start_idx = idx
    elif session.resume_policy == ResumePolicy.CONTINUE_CHECKPOINT:
        start_idx = max(0, min(checkpoint, idx))
    else:
        # Restart from the current sentence boundary.
        start_idx = 0
        for i in range(idx - 1, -1, -1):
            token = words[i].strip()
            if token.endswith(".") or token.endswith("!") or token.endswith("?"):
                start_idx = i + 1
                break

    return words[start_idx:]


async def _stream_tts_audio(
    websocket: WebSocket,
    session,
    text: str,
    response_id: str,
    generation: int,
) -> None:
    if tts_engine is None:
        return

    await _send_json(
        websocket,
        {
            "type": WsEvent.TTS_STREAM_START,
            "response_id": response_id,
            "format": "pcm16le",
            "sample_rate": 16000,
            "channels": 1,
        },
    )
    session.tts_state.active = True
    session.tts_state.response_id = response_id
    session.tts_state.voice = settings.tts_voice

    try:
        async for chunk in tts_engine.synthesize_stream(text, session.session_id):
            if session.interrupted or generation != session.response_generation:
                break
            if chunk:
                await websocket.send_bytes(chunk)
    finally:
        session.tts_state.active = False
        session.tts_state.response_id = None
        await _send_json(
            websocket,
            {
                "type": WsEvent.TTS_STREAM_END,
                "response_id": response_id,
            },
        )


async def _maybe_detect_live_wake_interrupt(
    websocket: WebSocket,
    session,
    session_id: str,
    chunk: bytes,
) -> bool:
    if not session.is_ai_speaking:
        live_wake_interrupt_buffers.pop(session_id, None)
        live_wake_interrupt_checked_bytes.pop(session_id, None)
        return False

    if wake_word_detector is None or not wake_word_detector.enabled:
        return False

    pcm_per_sec = 16000 * 2
    check_bytes = max(1, int((settings.live_interrupt_check_ms / 1000.0) * pcm_per_sec))
    max_bytes = max(check_bytes, int((settings.live_interrupt_buffer_ms / 1000.0) * pcm_per_sec))

    buffer = live_wake_interrupt_buffers.setdefault(session_id, bytearray())
    buffer.extend(chunk)
    if len(buffer) > max_bytes:
        del buffer[:-max_bytes]

    previous_checked = live_wake_interrupt_checked_bytes.get(session_id, 0)
    if len(buffer) - previous_checked < check_bytes:
        return False
    live_wake_interrupt_checked_bytes[session_id] = len(buffer)

    detection = await wake_word_detector.detect(bytes(buffer), sample_rate=16000)
    if not detection.detected or detection.confidence < settings.wake_interrupt_min_confidence:
        return False

    await _interrupt_active_response(websocket, session, trigger="wake_word")
    await _handle_wake_trigger(
        websocket,
        session,
        source=detection.source,
        confidence=detection.confidence,
    )
    live_wake_interrupt_buffers[session_id] = bytearray()
    live_wake_interrupt_checked_bytes[session_id] = 0
    return True


async def _collect_agent_response_text(
    transcript: str,
    session_id: str,
    *,
    input_mode: str = "chat",
    session_mode: str = "conversation",
    is_ai_speaking: bool = False,
) -> str:
    if agent_runner is None:
        return _build_demo_response_text(transcript, f"I heard: {transcript}")

    response_parts: list[str] = []
    async for event in agent_runner.run(
        transcript,
        session_id,
        context={
            "speaker_id": session_id,
            "input_mode": input_mode,
            "vayumi_state": {
                "mode": session_mode,
                "is_ai_speaking": is_ai_speaking,
            },
        },
    ):
        if event.event_type == "response_chunk" and event.content:
            response_parts.append(event.content)
        elif event.event_type == "response_end":
            break

    return "".join(response_parts).strip()


def _start_agent_response(
    websocket: WebSocket,
    session,
    transcript: str,
    respond_via: str = RespondVia.VOICE_AND_CHAT,
) -> None:
    _start_agent_response_with_policy(
        websocket,
        session,
        transcript,
        respond_via=respond_via,
        interrupt_policy=InterruptPolicy.REPLACE,
    )


def _queued_responses(session) -> list[dict]:
    queued = getattr(session, "_queued_responses", None)
    if queued is None:
        queued = []
        setattr(session, "_queued_responses", queued)
    return queued


def _start_agent_response_with_policy(
    websocket: WebSocket,
    session,
    transcript: str,
    respond_via: str = RespondVia.VOICE_AND_CHAT,
    interrupt_policy: str = InterruptPolicy.REPLACE,
) -> None:
    existing_task = active_response_tasks.get(session.session_id)
    if existing_task and not existing_task.done():
        if interrupt_policy == InterruptPolicy.QUEUE:
            _queued_responses(session).append(
                {
                    "transcript": transcript,
                    "respond_via": respond_via,
                }
            )
            logger.info("Queued response for session %s while AI speaking", session.session_id)
            return
        existing_task.cancel()

    session.interrupted = False
    session.response_generation += 1
    generation = session.response_generation

    response_task = asyncio.create_task(
        _run_agent_response(websocket, session, transcript, respond_via=respond_via, generation=generation)
    )
    active_response_tasks[session.session_id] = response_task

    def _cleanup(_task: asyncio.Task) -> None:
        active_response_tasks.pop(session.session_id, None)

    response_task.add_done_callback(_cleanup)


async def _run_agent_response(
    websocket: WebSocket,
    session,
    transcript: str,
    respond_via: str = RespondVia.VOICE_AND_CHAT,
    generation: int = 0,
) -> None:
    if agent_runner is None:
        return

    response_id = f"resp_{uuid.uuid4().hex[:8]}"
    session.current_response_id = response_id
    session.is_ai_speaking = True

    try:
        await _send_json(websocket, {"type": WsEvent.AGENT_THINKING})
        response_text = await _collect_agent_response_text(
            transcript,
            session.session_id,
            input_mode="voice" if respond_via != RespondVia.CHAT_ONLY else "chat",
            session_mode=session.mode.value,
            is_ai_speaking=session.is_ai_speaking,
        )
        if not response_text:
            response_text = "Working on it."

        await _send_json(
            websocket,
            {
                "type": WsEvent.AGENT_RESPONSE_START,
                "response_id": response_id,
                "text": response_text[:80],
            },
        )

        # Typed chat should feel immediate: skip paced token streaming and TTS.
        if respond_via == RespondVia.CHAT_ONLY:
            await _send_json(
                websocket,
                {
                    "type": WsEvent.CHATBOT_RESPONSE,
                    "text": response_text,
                    "spoken": False,
                    "response_id": response_id,
                },
            )
            await _send_json(websocket, {"type": WsEvent.AGENT_RESPONSE_END, "response_id": response_id})
            session.pending_resume_words = []
            session.pending_resume_response_id = None
            return

        streamed_words: list[str] = []
        words = response_text.split()
        session.current_response_words = words
        session.current_response_word_index = 0
        session.current_response_checkpoint_index = 0

        for idx, word in enumerate(words):
            if session.interrupted or generation != session.response_generation:
                break
            streamed_words.append(word)
            await _send_json(
                websocket,
                {
                    "type": WsEvent.AGENT_RESPONSE_CHUNK,
                    "response_id": response_id,
                    "text": f"{word} ",
                },
            )
            session.current_response_word_index = idx + 1
            if (idx + 1) % 8 == 0:
                session.current_response_checkpoint_index = idx + 1
            chunk_delay_seconds = max(0.0, settings.agent_chunk_delay_ms / 1000.0)
            if chunk_delay_seconds > 0:
                await asyncio.sleep(chunk_delay_seconds)
            if session.interrupted or generation != session.response_generation:
                break

        final_text = " ".join(streamed_words).strip() or response_text
        if session.interrupted or generation != session.response_generation:
            return

        if respond_via != RespondVia.CHAT_ONLY:
            try:
                await _stream_tts_audio(websocket, session, final_text, response_id, generation)
            except Exception as exc:
                logger.exception("TTS stream failed for session %s", session.session_id)
                await _send_error(websocket, "tts_failed", str(exc), fatal=False)

        await _send_json(
            websocket,
            {
                "type": WsEvent.CHATBOT_RESPONSE,
                "text": final_text,
                "spoken": respond_via != RespondVia.CHAT_ONLY,
                "response_id": response_id,
            },
        )
        if not session.interrupted:
            await _send_json(websocket, {"type": WsEvent.AGENT_RESPONSE_END, "response_id": response_id})
            session.pending_resume_words = []
            session.pending_resume_response_id = None
    finally:
        session.current_response_words = []
        session.current_response_word_index = 0
        session.current_response_checkpoint_index = 0
        session.is_ai_speaking = False
        setattr(session, "_last_ai_ended_at", datetime.utcnow())
        live_wake_interrupt_buffers.pop(session.session_id, None)
        live_wake_interrupt_checked_bytes.pop(session.session_id, None)
        active_response_tasks.pop(session.session_id, None)

        queued = _queued_responses(session)
        if queued and websocket.client_state == WebSocketState.CONNECTED:
            next_item = queued.pop(0)
            _start_agent_response_with_policy(
                websocket,
                session,
                next_item["transcript"],
                respond_via=next_item.get("respond_via", RespondVia.VOICE_AND_CHAT),
                interrupt_policy=InterruptPolicy.REPLACE,
            )


async def _handle_speech_segment(websocket: WebSocket, session, session_id: str) -> None:
    if audio_pipeline is None:
        await _send_error(websocket, "audio_pipeline_unavailable", "Audio pipeline unavailable", fatal=False)
        return

    audio_data = await audio_pipeline.get_buffered_audio(session_id)
    if not audio_data:
        await _send_json(
            websocket,
            {
                "type": WsEvent.TRANSCRIPTION_FINAL,
                "text": "",
                "confidence": 0.0,
                "speaker_label": None,
                "is_owner": None,
            },
        )
        return

    if session.mode == Mode.MEETING:
        acc = meeting_audio_accumulators.setdefault(session_id, bytearray())
        acc.extend(audio_data)
        buffered_audio = bytes(acc)
        duration_ms = (len(buffered_audio) * 1000) // (16000 * 2)
        if duration_ms < settings.meeting_min_transcribe_segment_ms:
            logger.info(
                "Accumulating meeting audio for session %s (%sms < %sms)",
                session_id,
                duration_ms,
                settings.meeting_min_transcribe_segment_ms,
            )
            return
        audio_data = buffered_audio
        meeting_audio_accumulators[session_id] = bytearray()
    else:
        duration_ms = (len(audio_data) * 1000) // (16000 * 2)
        if duration_ms < settings.min_transcribe_segment_ms:
            logger.info(
                "Skipped short segment for session %s (%sms < %sms)",
                session_id,
                duration_ms,
                settings.min_transcribe_segment_ms,
            )
            return

    now = datetime.utcnow()
    last_ai_ended_at = getattr(session, "_last_ai_ended_at", None)
    recently_ai_spoke = (
        last_ai_ended_at is not None
        and (now - last_ai_ended_at).total_seconds() < settings.self_echo_suppression_seconds
    )

    # While AI is speaking (or just after), only allow wake-word based interrupt/open-window.
    if session.is_ai_speaking or recently_ai_spoke:
        if wake_word_detector is not None and wake_word_detector.enabled:
            detection = await wake_word_detector.detect(audio_data, sample_rate=16000)
            is_valid_wake_interrupt = detection.detected and detection.confidence >= settings.wake_interrupt_min_confidence
            if is_valid_wake_interrupt:
                if session.is_ai_speaking:
                    await _interrupt_active_response(websocket, session, trigger="wake_word")
                await _handle_wake_trigger(
                    websocket,
                    session,
                    source=detection.source,
                    confidence=detection.confidence,
                )
                return

        logger.info(
            "Suppressed likely self-echo for session %s (ai_speaking=%s recent=%s)",
            session_id,
            session.is_ai_speaking,
            recently_ai_spoke,
        )
        return

    wake_window_open = session.is_wake_window_open()
    require_wake_in_transcript = False
    if session.mode != Mode.MEETING and not wake_window_open and wake_word_detector is not None and wake_word_detector.enabled:
        detection = await wake_word_detector.detect(audio_data, sample_rate=16000)
        if not detection.detected:
            logger.info(
                "Skipped STT for session %s (wake not detected, confidence=%.3f)",
                session_id,
                detection.confidence,
            )
            if detection.transcript:
                await _send_json(
                    websocket,
                    {
                        "type": "wake_word_debug",
                        "text": detection.transcript,
                    },
                )
            await _send_json(
                websocket,
                {
                    "type": WsEvent.WAKE_WORD_REQUIRED,
                    "message": "Say Vayumi before your command.",
                },
            )
            return
        # Detector hit only gates STT work; we still require explicit wake word
        # in the transcript before opening the command window.
        require_wake_in_transcript = True

    try:
        transcription = await audio_pipeline.transcribe_audio(session_id, audio_data)
    except Exception as exc:
        logger.exception("Audio transcription failed for session %s", session_id)
        await _send_error(websocket, "stt_failed", str(exc), fatal=False)
        return

    if transcription is not None:
        if session.mode == Mode.MEETING:
            await _finalize_meeting_transcription(
                websocket,
                session,
                transcription,
                audio_data=audio_data,
                duration_ms=duration_ms,
            )
            return

        await _finalize_transcription(
            websocket,
            session,
            transcription,
            require_wake_in_transcript=require_wake_in_transcript,
        )


async def _finalize_meeting_transcription(
    websocket: WebSocket,
    session,
    result: TranscriptionResult,
    audio_data: bytes,
    duration_ms: int,
) -> None:
    text = (result.text or "").strip()
    if not text:
        return

    start_ms = max(0, session.meeting_timeline_ms)
    end_ms = start_ms + max(0, duration_ms)

    segments = []
    if diarization_engine is not None:
        segments = await diarization_engine.diarize(
            audio_data,
            session_id=session.session_id,
            text=text,
            speaker_hint=result.speaker_label,
            start_ms=start_ms,
            end_ms=end_ms,
        )

    if not segments:
        fallback_speaker = result.speaker_label or "speaker_0"
        segments = [
            {
                "speaker": fallback_speaker,
                "start_ms": start_ms,
                "end_ms": end_ms,
                "text": text,
                "confidence": result.confidence,
            }
        ]
    else:
        segments = [
            {
                "speaker": seg.speaker,
                "start_ms": seg.start_ms,
                "end_ms": seg.end_ms,
                "text": seg.text or text,
                "confidence": seg.confidence,
            }
            for seg in segments
        ]

    for seg in segments:
        session.transcriptions.append(
            TranscriptionSegment(
                text=seg["text"],
                start_ms=seg["start_ms"],
                end_ms=seg["end_ms"],
                confidence=result.confidence,
                final=True,
                speaker=seg["speaker"],
            )
        )
        session.meeting_segments.append(
            DiarizationSegment(
                speaker=seg["speaker"],
                text=seg["text"],
                start_ms=seg["start_ms"],
                end_ms=seg["end_ms"],
            )
        )
        await _send_json(
            websocket,
            {
                "type": WsEvent.DIARIZATION_SEGMENT,
                "speaker": seg["speaker"],
                "text": seg["text"],
                "start_ms": seg["start_ms"],
                "end_ms": seg["end_ms"],
                "confidence": seg["confidence"],
            },
        )

    session.last_speaker_label = segments[-1]["speaker"]
    session.last_speaker_confidence = result.confidence
    session.last_speaker_is_owner = result.is_owner
    session.meeting_timeline_ms = end_ms

    await _send_json(
        websocket,
        {
            "type": WsEvent.TRANSCRIPTION_FINAL,
            "text": text,
            "confidence": result.confidence,
            "speaker_label": segments[-1]["speaker"],
            "is_owner": result.is_owner,
            "mode": "meeting",
            "start_ms": start_ms,
            "end_ms": end_ms,
        },
    )


async def _finalize_transcription(
    websocket: WebSocket,
    session,
    result: TranscriptionResult,
    respond_via: str = RespondVia.VOICE_AND_CHAT,
    require_wake_in_transcript: bool = False,
) -> None:
    if not result.text:
        return

    has_wake_word, cleaned_text = _strip_wake_word(result.text)
    if require_wake_in_transcript and not has_wake_word:
        logger.info(
            "Rejected transcript without explicit wake word for session %s: %s",
            session.session_id,
            result.text[:80],
        )
        await _send_json(
            websocket,
            {
                "type": WsEvent.WAKE_WORD_REQUIRED,
                "message": "Say Vayumi before your command.",
            },
        )
        return

    if has_wake_word:
        if session.is_ai_speaking:
            await _interrupt_active_response(websocket, session, trigger="wake_word")
        await _handle_wake_trigger(websocket, session)

        if not cleaned_text:
            logger.info("Wake word detected without command for session %s", session.session_id)
            return
    elif not session.is_wake_window_open():
        logger.info("Ignoring transcript without active wake window for session %s: %s", session.session_id, result.text[:80])
        await _send_json(
            websocket,
            {
                "type": WsEvent.WAKE_WORD_REQUIRED,
                "message": "Say Vayumi before your command.",
            },
        )
        return

    now = datetime.utcnow()
    last_command_at = getattr(session, "_last_command_at", None)
    if last_command_at is not None:
        delta = (now - last_command_at).total_seconds()
        if delta < settings.min_command_gap_seconds:
            logger.info(
                "Dropped rapid follow-up for session %s (%.2fs < %.2fs)",
                session.session_id,
                delta,
                settings.min_command_gap_seconds,
            )
            return
    setattr(session, "_last_command_at", now)

    wake_status = "command-window-open"
    if settings.wake_single_command_mode:
        _close_wake_window(session)
        wake_status = "sleeping"
    elif session.is_wake_window_open():
        session.wake_window_expires_at = now + timedelta(seconds=settings.wake_command_window_seconds)

    final_text = cleaned_text or result.text
    session.wake_word_active = False
    await _send_json(
        websocket,
        {
            "type": WsEvent.WAKE_WORD_STATUS,
            "status": wake_status,
        },
    )

    session.last_speaker_label = result.speaker_label
    session.last_speaker_confidence = result.confidence
    session.last_speaker_is_owner = result.is_owner

    segment = TranscriptionSegment(
        text=final_text,
        start_ms=0,
        end_ms=0,
        confidence=result.confidence,
        final=True,
        speaker=result.speaker_label,
    )
    session.transcriptions.append(segment)

    await _send_json(
        websocket,
        {
            "type": WsEvent.TRANSCRIPTION_FINAL,
            "text": final_text,
            "confidence": result.confidence,
            "speaker_label": result.speaker_label,
            "is_owner": result.is_owner,
        },
    )

    if result.speaker_label:
        await _send_json(
            websocket,
            {
                "type": WsEvent.SPEAKER_IDENTIFIED,
                "speaker_label": result.speaker_label,
                "confidence": result.confidence,
                "is_owner": result.is_owner,
            },
        )

    _start_agent_response_with_policy(
        websocket,
        session,
        final_text,
        respond_via=respond_via,
        interrupt_policy=InterruptPolicy.REPLACE,
    )


@app.post("/chat")
async def chat_fallback(message: ChatRequest, current_user: UserRecord = Depends(_get_current_user)):
    transcript = message.text.strip()
    if not transcript:
        raise HTTPException(status_code=400, detail="Chat message text is required")

    attachments = message.attachments or []

    routed_via = "http"
    if message.session_id and message.session_id in active_websockets and session_manager is not None:
        owner_id = session_owner_map.get(message.session_id)
        if owner_id and owner_id != current_user.id:
            raise HTTPException(status_code=403, detail="Session does not belong to current user")
        session = await session_manager.get_session(message.session_id)
        websocket = active_websockets.get(message.session_id)
        if session is not None and websocket is not None and websocket.client_state == WebSocketState.CONNECTED:
            _record_session_attachments(session, attachments)
            transcript = await _compose_transcript_with_attachments(transcript, attachments)
            _start_agent_response_with_policy(
                websocket,
                session,
                transcript,
                respond_via=message.respond_via,
                interrupt_policy=message.interrupt_policy,
            )
            routed_via = "websocket"

            return ChatResponsePayload(
                response_id=f"resp_{uuid.uuid4().hex[:8]}",
                text="",
                spoken=message.respond_via != RespondVia.CHAT_ONLY,
                routed_via=routed_via,
                session_id=message.session_id,
            )

    response_id = f"resp_{uuid.uuid4().hex[:8]}"
    if message.session_id and session_manager is not None:
        session = await session_manager.get_session(message.session_id)
        if session is not None:
            _record_session_attachments(session, attachments)
    transcript = await _compose_transcript_with_attachments(transcript, attachments)
    response_text = await _collect_agent_response_text(transcript, message.session_id or f"http_{uuid.uuid4().hex[:8]}")

    return ChatResponsePayload(
        response_id=response_id,
        text=response_text,
        spoken=False,
        routed_via=routed_via,
        session_id=message.session_id,
    )


@app.post("/session/{session_id}/resume")
async def resume_session_response(session_id: str, current_user: UserRecord = Depends(_get_current_user)):
    owner_id = session_owner_map.get(session_id)
    if owner_id and owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Session does not belong to current user")

    if session_manager is None:
        raise HTTPException(status_code=503, detail="Session manager unavailable")

    session = await session_manager.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    if not session.pending_resume_words:
        raise HTTPException(status_code=409, detail="No resumable response available")

    websocket = active_websockets.get(session_id)
    if websocket is None or websocket.client_state != WebSocketState.CONNECTED:
        raise HTTPException(status_code=409, detail="No active websocket for this session")

    resume_text = " ".join(session.pending_resume_words).strip()
    session.pending_resume_words = []
    _start_agent_response_with_policy(
        websocket,
        session,
        resume_text,
        respond_via=RespondVia.VOICE_AND_CHAT,
        interrupt_policy=InterruptPolicy.REPLACE,
    )
    return {
        "status": "resumed",
        "policy": session.resume_policy.value,
        "session_id": session_id,
    }


@app.post("/session/{session_id}/resume-policy")
async def set_resume_policy(
    session_id: str,
    payload: ResumePolicyRequest,
    current_user: UserRecord = Depends(_get_current_user),
):
    owner_id = session_owner_map.get(session_id)
    if owner_id and owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Session does not belong to current user")

    if session_manager is None:
        raise HTTPException(status_code=503, detail="Session manager unavailable")

    session = await session_manager.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    try:
        policy = ResumePolicy(payload.policy)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid resume policy")

    session.resume_policy = policy
    return {
        "status": "ok",
        "policy": session.resume_policy.value,
        "session_id": session_id,
    }


@app.post("/session/{session_id}/speak")
async def speak_in_session(
    session_id: str,
    payload: SpeakRequest,
    current_user: UserRecord = Depends(_get_current_user),
):
    owner_id = session_owner_map.get(session_id)
    if owner_id and owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Session does not belong to current user")

    if session_manager is None:
        raise HTTPException(status_code=503, detail="Session manager unavailable")

    session = await session_manager.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    websocket = active_websockets.get(session_id)
    if websocket is None or websocket.client_state != WebSocketState.CONNECTED:
        raise HTTPException(status_code=409, detail="No active websocket for this session")

    text = payload.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="Text is required")

    _start_agent_response_with_policy(
        websocket,
        session,
        text,
        respond_via=payload.respond_via,
        interrupt_policy=InterruptPolicy.REPLACE,
    )
    return {
        "status": "queued",
        "session_id": session_id,
        "text_preview": text[:80],
    }


@app.post("/auth/register")
async def register_user(payload: RegisterRequest):
    if auth_service is None:
        raise HTTPException(status_code=503, detail="Auth service unavailable")
    email = payload.email.strip().lower()
    password = payload.password

    if "@" not in email or len(email) < 5:
        raise HTTPException(status_code=400, detail="Invalid email")
    if len(password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters")

    try:
        user = await auth_service.register(email=email, password=password, name=payload.name)
    except Exception as exc:
        msg = str(exc).lower()
        if "duplicate" in msg or "unique" in msg:
            raise HTTPException(status_code=409, detail="Email already exists")
        raise

    token = auth_service.create_access_token(user)
    return {
        "user": {
            "id": user.id,
            "email": user.email,
            "name": user.name,
        },
        "access_token": token,
        "token_type": "bearer",
    }


@app.post("/auth/login")
async def login_user(payload: LoginRequest):
    if auth_service is None:
        raise HTTPException(status_code=503, detail="Auth service unavailable")

    user = await auth_service.login(payload.email, payload.password)
    if user is None:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    token = auth_service.create_access_token(user)
    return {
        "user": {
            "id": user.id,
            "email": user.email,
            "name": user.name,
        },
        "access_token": token,
        "token_type": "bearer",
    }


@app.get("/auth/me")
async def get_me(current_user: UserRecord = Depends(_get_current_user)):
    return {
        "id": current_user.id,
        "email": current_user.email,
        "name": current_user.name,
    }


async def _handle_audio_message(session_id: str, message: dict, websocket: WebSocket, session) -> None:
    msg_type = message.get("type")

    if msg_type == "audio_stream_start":
        trigger = message.get("trigger", "unknown")
        session.is_vad_active = True
        logger.info("Audio stream started (trigger=%s) for session %s", trigger, session_id)
        await _send_json(websocket, {"type": WsEvent.VAD_SPEECH_START})
        return

    if msg_type == "audio_stream_end":
        reason = message.get("reason", "unknown")
        duration_ms = message.get("duration_ms", 0)
        session.is_vad_active = False
        logger.info("Audio stream ended (reason=%s, duration=%sms)", reason, duration_ms)

        await _send_json(websocket, {"type": WsEvent.VAD_SPEECH_END})
        await _handle_speech_segment(websocket, session, session_id)
        return

    if msg_type == "interrupt":
        trigger = message.get("trigger", "unknown")
        confidence = message.get("wake_confidence", 0.0)
        logger.info("Interrupt received (trigger=%s, confidence=%s)", trigger, confidence)

        await _interrupt_active_response(websocket, session, trigger=trigger)
        session.interrupted = False
        session.is_ai_speaking = False
        _open_wake_window(session, settings.wake_command_window_seconds)
        await _send_json(
            websocket,
            {
                "type": WsEvent.WAKE_WORD_STATUS,
                "status": "command-window-open",
            },
        )
        await _send_json(
            websocket,
            {
                "type": WsEvent.WAKE_WORD_DETECTED,
                "source": trigger,
                "confidence": confidence,
            },
        )
        await _send_json(websocket, {"type": WsEvent.VAD_SPEECH_START})
        return

    if msg_type == "ping":
        await _send_json(
            websocket,
            {
                "type": WsEvent.PONG,
                "ts": message.get("ts"),
                "server_ts": datetime.utcnow().timestamp(),
            },
        )


async def _handle_control_message(session_id: str, message: dict, websocket: WebSocket, session) -> None:
    msg_type = message.get("type")

    if msg_type == "mode_switch":
        mode_str = message.get("mode", "conversation")
        try:
            mode = Mode(mode_str)
        except ValueError:
            await _send_error(websocket, "invalid_mode", f"Invalid mode: {mode_str}", fatal=False)
            return

        session.mode = mode
        if mode == Mode.MEETING:
            session.meeting_timeline_ms = 0
            session.meeting_segments = []
            meeting_audio_accumulators[session_id] = bytearray()
        else:
            meeting_audio_accumulators.pop(session_id, None)
        logger.info("Session %s switched to mode %s", session_id, mode.value)

        await _send_json(
            websocket,
            {
                "type": WsEvent.MODE_CHANGED,
                "mode": mode.value,
                "features": {
                    "diarization": mode == Mode.MEETING,
                    "vad_sensitivity": "high" if mode == Mode.MEETING else "normal",
                    "wake_word_in_meeting": True,
                },
            },
        )
        return

    if msg_type == "chatbot_message":
        transcript = message.get("text", "").strip()
        if not transcript:
            await _send_error(websocket, "empty_chat_message", "Chat message text is required", fatal=False)
            return

        attachments = message.get("attachments") or []
        _record_session_attachments(session, attachments)
        transcript = await _compose_transcript_with_attachments(transcript, attachments)

        _start_agent_response_with_policy(
            websocket,
            session,
            transcript,
            respond_via=message.get("respond_via", RespondVia.CHAT_ONLY),
            interrupt_policy=message.get("interrupt_policy", InterruptPolicy.QUEUE),
        )
        return

    if msg_type == "resume_response":
        if not session.pending_resume_words:
            await _send_error(websocket, "resume_unavailable", "No resumable response available", fatal=False)
            return
        resume_text = " ".join(session.pending_resume_words).strip()
        session.pending_resume_words = []
        _start_agent_response_with_policy(
            websocket,
            session,
            resume_text,
            respond_via=RespondVia.VOICE_AND_CHAT,
            interrupt_policy=InterruptPolicy.REPLACE,
        )
        return

    if msg_type == "set_resume_policy":
        policy_str = message.get("policy", "")
        try:
            session.resume_policy = ResumePolicy(policy_str)
        except ValueError:
            await _send_error(websocket, "invalid_resume_policy", f"Invalid resume policy: {policy_str}", fatal=False)
            return
        await _send_json(
            websocket,
            {
                "type": WsEvent.RESUME_POLICY_CHANGED,
                "policy": session.resume_policy.value,
            },
        )
        return


async def _create_session_for_websocket(client_type: ClientType, websocket: WebSocket, user: UserRecord) -> tuple[str, object]:
    if session_manager is None:
        raise RuntimeError("Session manager is not initialized")

    session = await session_manager.create_session()
    session.user_id = user.id
    session_id = session.session_id
    active_websockets[session_id] = websocket
    session_owner_map[session_id] = user.id

    await _send_json(
        websocket,
        {
            "type": WsEvent.HELLO,
            "session_id": session_id,
            "user_id": user.id,
            "server_version": "1.0.0",
            "client_type_accepted": client_type.value,
            "modes": [Mode.CONVERSATION.value, Mode.MEETING.value],
            "wake_word": "vayumi",
            "features": {
                "groq_stt": True,
                "local_wake_detector": bool(wake_word_detector and wake_word_detector.enabled),
                "speaker_identity": True,
                "chatbot": True,
            },
        },
    )

    return session_id, session


async def _run_websocket_session(websocket: WebSocket, client_type: ClientType) -> None:
    session_id: Optional[str] = None
    try:
        # Validate auth token before accepting websocket to avoid noisy traceback logs.
        user = await _require_ws_user(websocket)

        await websocket.accept()
        logger.info("%s client connected", client_type.value.capitalize())

        session_id, session = await _create_session_for_websocket(client_type, websocket, user)

        try:
            ready_message = await websocket.receive_json()
        except Exception as exc:
            await _send_error(websocket, "client_ready_failed", str(exc), fatal=True)
            return

        if ready_message.get("type") != "client_ready":
            await _send_error(websocket, "protocol_error", "Expected client_ready after hello", fatal=True)
            return

        client_ready_type = ClientType(ready_message.get("client_type", client_type.value))
        capabilities = ready_message.get("capabilities", [])
        audio_config_dict = ready_message.get("audio_config", {})
        audio_config = AudioConfig(
            sample_rate=audio_config_dict.get("sample_rate", 16000),
            channels=audio_config_dict.get("channels", 1),
            bit_depth=audio_config_dict.get("bit_depth", 16),
        )

        await session_manager.register_client(session_id, client_ready_type, capabilities, audio_config)
        session = await session_manager.get_session(session_id)

        await _send_json(
            websocket,
            {
                "type": WsEvent.SESSION_STARTED,
                "session_id": session_id,
                "active": True,
            },
        )
        logger.info("Session %s established with %s client", session_id, client_ready_type.value)

        while True:
            try:
                data = await asyncio.wait_for(websocket.receive(), timeout=5.0)
                if data.get("type") == "websocket.disconnect":
                    break

                if "bytes" in data and data["bytes"] is not None:
                    await _expire_wake_window_if_needed(websocket, session)
                    chunk = data["bytes"]
                    if await _maybe_detect_live_wake_interrupt(websocket, session, session_id, chunk):
                        continue

                    # During AI speech, only live wake interrupt checks are processed.
                    if session.is_ai_speaking:
                        continue

                    vad_event = await audio_pipeline.process_chunk(session_id, chunk)
                    if vad_event is not None:
                        event_type = WsEvent.VAD_SPEECH_START if vad_event.is_speech else WsEvent.VAD_SPEECH_END
                        await _send_json(
                            websocket,
                            {
                                "type": event_type,
                            },
                        )
                        if not vad_event.is_speech:
                            await _handle_speech_segment(websocket, session, session_id)
                elif "text" in data and data["text"]:
                    await _expire_wake_window_if_needed(websocket, session)
                    try:
                        message = json.loads(data["text"])
                    except json.JSONDecodeError as exc:
                        await _send_error(websocket, "json_decode_error", str(exc), fatal=False)
                        continue

                    msg_type = message.get("type")
                    if msg_type in {"audio_stream_start", "audio_stream_end", "interrupt", "ping"}:
                        await _handle_audio_message(session_id, message, websocket, session)
                    else:
                        await _handle_control_message(session_id, message, websocket, session)

            except asyncio.TimeoutError:
                continue
            except WebSocketDisconnect:
                break

    except HTTPException as exc:
        # Expected path for missing/invalid websocket auth token.
        logger.info("WebSocket rejected (%s): %s", exc.status_code, exc.detail)
        if websocket.client_state == WebSocketState.CONNECTING:
            await websocket.close(code=1008, reason=str(exc.detail))
        elif websocket.client_state == WebSocketState.CONNECTED:
            await _send_error(websocket, "auth_error", str(exc.detail), fatal=True)
            await websocket.close(code=1008, reason=str(exc.detail))
    except Exception as exc:
        logger.error("WebSocket error: %s", exc, exc_info=True)
        if session_id is not None:
            await _send_error(websocket, "websocket_error", str(exc), fatal=False)
    finally:
        if session_id is not None and session_manager is not None:
            await session_manager.unregister_client(session_id, client_type)
            active_websockets.pop(session_id, None)
            session_owner_map.pop(session_id, None)
            live_wake_interrupt_buffers.pop(session_id, None)
            live_wake_interrupt_checked_bytes.pop(session_id, None)
            meeting_audio_accumulators.pop(session_id, None)
            response_task = active_response_tasks.pop(session_id, None)
            if response_task and not response_task.done():
                response_task.cancel()
        if websocket.client_state == WebSocketState.CONNECTED:
            await websocket.close()
        logger.info("%s client disconnected (session=%s)", client_type.value.capitalize(), session_id)


@app.get("/health")
async def health_check():
    active_count = await session_manager.get_active_sessions_count()
    return {
        "status": "ok",
        "active_sessions": active_count,
        "timestamp": datetime.utcnow().isoformat(),
        "stt_provider": settings.stt_provider,
        "wake_detector_provider": settings.wake_detector_provider,
        "groq_configured": bool(settings.groq_api_key),
    }


@app.get("/session/{session_id}/status")
async def get_session_status(session_id: str, current_user: UserRecord = Depends(_get_current_user)):
    owner_id = session_owner_map.get(session_id)
    if owner_id and owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Session does not belong to current user")

    session = await session_manager.get_session(session_id)
    if not session:
        return {"status": "not_found"}

    return {
        "status": "active" if session.has_connected_clients() else "idle",
        "mode": session.mode.value,
        "resume_policy": session.resume_policy.value,
        "voice_source": session.active_voice_source.value if session.active_voice_source else None,
        "web_connected": session.web_client is not None,
        "hardware_connected": session.hardware_client is not None,
        "is_vad_active": session.is_vad_active,
        "is_ai_speaking": session.is_ai_speaking,
        "tts_active": session.tts_state.active,
        "tts_response_id": session.tts_state.response_id,
        "last_speaker_label": session.last_speaker_label,
        "last_speaker_confidence": session.last_speaker_confidence,
        "last_speaker_is_owner": session.last_speaker_is_owner,
        "meeting_timeline_ms": session.meeting_timeline_ms,
        "meeting_segments_count": len(session.meeting_segments),
    }


@app.websocket("/ws/audio")
async def websocket_audio(websocket: WebSocket):
    await _run_websocket_session(websocket, ClientType.WEB)


@app.websocket("/ws/hardware")
async def websocket_hardware(websocket: WebSocket):
    await _run_websocket_session(websocket, ClientType.HARDWARE)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=settings.host, port=settings.port)