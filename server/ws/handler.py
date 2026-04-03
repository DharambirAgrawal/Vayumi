# =============================================================================
# server/ws/handler.py — Unified WebSocket Handler (Single Entry Point)
# =============================================================================

import asyncio
import base64
import logging
import re
from typing import AsyncIterator, Union

from fastapi import WebSocket, WebSocketDisconnect

from server.auth.jwt_handler import validate_token
from server.ws.session import Session, create_session
from server.core.orchestrator import Orchestrator
from server.core.context_builder import ContextBuilder
from server.core.interrupt_handler import InterruptHandler
from server.core.mode_manager import ModeManager
from server.agents.memory_agent import MemoryAgent
from server.skills.skill_runner import SkillRunner
from server.agents.task_agent import TaskAgent
from server.agents.search_agent import SearchAgent
from server.agents.persona_agent import PersonaAgent
from server.voice.stt import STTEngine
from server.voice.tts import TTSEngine, pcm_to_wav
from server.voice.vad import VADEngine
from server.voice.diarizer import SpeakerIdentifier

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level session store — keyed by session_id
# ---------------------------------------------------------------------------
active_sessions: dict[str, Session] = {}

CANCEL_WORDS = {"never mind", "cancel", "forget it", "stop", "don't bother"}

# ---------------------------------------------------------------------------
# Shared service singletons (initialised lazily on first connection)
# ---------------------------------------------------------------------------
_orchestrator: Orchestrator | None = None
_context_builder: ContextBuilder | None = None
_interrupt_handler: InterruptHandler | None = None
_mode_manager: ModeManager | None = None
_memory_agent: MemoryAgent | None = None
_persona_agent: PersonaAgent | None = None
_stt: STTEngine | None = None
_tts: TTSEngine | None = None
_vad: VADEngine | None = None
_diarizer: SpeakerIdentifier | None = None
_skill_runner: SkillRunner | None = None


def _ensure_services(app_state=None):
    """Lazy-init shared service instances from FastAPI app.state."""
    global _orchestrator, _context_builder, _interrupt_handler, _mode_manager
    global _memory_agent, _persona_agent, _stt, _tts, _vad, _diarizer, _skill_runner

    if _orchestrator is not None:
        return

    if app_state is None:
        raise RuntimeError("WS services are not initialized: missing app state")

    llm_router = getattr(app_state, "llm_router")
    sqlite_store = getattr(app_state, "sqlite_store")
    vector_store = getattr(app_state, "vector_store")
    embedder = getattr(app_state, "embedder")
    skill_runner = getattr(app_state, "skill_runner")
    mcp_runner = getattr(app_state, "mcp_runner")
    _skill_runner = skill_runner

    _stt = getattr(app_state, "stt")
    _tts = getattr(app_state, "tts")
    _vad = getattr(app_state, "vad")
    _diarizer = getattr(app_state, "diarizer")

    _context_builder = ContextBuilder(
        vector_store=vector_store,
        sqlite_store=sqlite_store,
        embedder=embedder,
        skill_registry=getattr(skill_runner, "registry", {}),
        mcp_registry=getattr(mcp_runner, "registry", {}),
    )
    _memory_agent = MemoryAgent(
        llm_router=llm_router,
        vector_store=vector_store,
        sqlite_store=sqlite_store,
        embedder=embedder,
    )
    task_agent = TaskAgent(
        llm_router=llm_router,
        skill_runner=skill_runner,
        mcp_runner=mcp_runner,
    )
    search_agent = SearchAgent(
        llm_router=llm_router,
        mcp_runner=mcp_runner,
    )
    _orchestrator = Orchestrator(
        llm_router=llm_router,
        context_builder=_context_builder,
        task_agent=task_agent,
        search_agent=search_agent,
        memory_agent=_memory_agent,
        skill_runner=skill_runner,
        mcp_runner=mcp_runner,
    )
    _interrupt_handler = InterruptHandler(
        tts_engine=_tts,
        stt_engine=_stt,
        diarizer=_diarizer,
    )
    _mode_manager = ModeManager(llm_router=llm_router, memory_store=sqlite_store)
    _persona_agent = PersonaAgent(sqlite_store=sqlite_store, diarizer=_diarizer)


def _append_turn(session: Session, role: str, text: str, speaker_id: str | None = None) -> None:
    """Store a conversation turn using the field names the rest of the stack expects."""
    if not text:
        return

    session.working_memory.append({
        "role": role,
        "content": text,
        "text": text,
        "speaker_id": speaker_id or session.user_id,
    })


# ---------------------------------------------------------------------------
# Active-window timer helper (30 s inactivity → SLEEP)
# ---------------------------------------------------------------------------
ACTIVE_WINDOW_SECONDS = 30.0

_URL_PATTERN = re.compile(r"(?:https?://|www\.)\S+", re.IGNORECASE)
_AUTHOR_QUESTION_PATTERN = re.compile(
    r"\b(who\s+(?:is\s+)?(?:the\s+)?author|who\s+wrote|who\s+is\s+credited|author\s+of\s+(?:this|that|the)\s+article|what\s+is\s+the\s+author)\b",
    re.IGNORECASE,
)


def _reset_active_timer(session: Session):
    """Cancel any existing timer and start a fresh 30 s window."""
    timer: asyncio.TimerHandle | asyncio.Task | None = getattr(session, "_active_timer", None)
    if timer is not None:
        timer.cancel()

    async def _expire():
        await asyncio.sleep(ACTIVE_WINDOW_SECONDS)
        session.activation_state = "SLEEP"
        logger.info("Session %s timed out → SLEEP", session.session_id)
        try:
            await send_status(session, "sleep")
        except Exception:
            pass

    session._active_timer = asyncio.ensure_future(_expire())


# ========================================================================= #
#  MESSAGE HANDLERS                                                         #
# ========================================================================= #

async def handle_wake(session: Session, msg: dict):
    """Activate the session, reset the inactivity timer, notify client."""
    logger.info("Wake received for session=%s", session.session_id)
    session.activation_state = "ACTIVE"
    _reset_active_timer(session)
    await send_status(session, "listening")


async def handle_audio_chunk(session: Session, msg: dict):
    """Process an incoming audio chunk (VAD → STT → diarize → turn)."""
    _ensure_services(session.websocket.app.state)

    # Ignore audio while sleeping
    if session.activation_state == "SLEEP":
        logger.debug("Ignoring audio chunk while session=%s is asleep", session.session_id)
        return

    # Decode base64 audio payload
    raw_audio = base64.b64decode(msg.get("data", ""))
    logger.debug("Audio chunk received session=%s bytes=%d", session.session_id, len(raw_audio))

    # VAD — echo-aware speech detection
    vad_result = await _vad.process(raw_audio, session)
    if not vad_result.has_speech:
        logger.debug("VAD rejected chunk session=%s", session.session_id)
        return

    # If the assistant is currently speaking, treat incoming speech as interrupt
    if session.activation_state == "SPEAKING":
        logger.info("Speech interrupt detected session=%s", session.session_id)
        await _interrupt_handler.handle_speech_interrupt(session, raw_audio)
        return

    # STT transcribe
    text = await _stt.transcribe(raw_audio)
    if not text or not text.strip():
        logger.debug("STT produced no text session=%s", session.session_id)
        return

    # Diarize — identify who is speaking
    speaker_id = await _diarizer.identify(raw_audio, session.user_id)
    logger.info("Voice input session=%s speaker=%s text=%r", session.session_id, speaker_id, text[:120])

    # Reset inactivity timer on valid speech
    _reset_active_timer(session)

    # Converge into the single processing path
    await process_user_turn(session, text, speaker_id, source="voice")


async def handle_text_input(session: Session, msg: dict):
    """Handle typed text from the client."""
    text = msg.get("text", "").strip()
    if not text:
        return

    logger.info("Text input session=%s text=%r", session.session_id, text[:160])

    # Auto-activate from SLEEP
    if session.activation_state == "SLEEP":
        logger.info("Text input re-activating sleeping session=%s", session.session_id)
        session.activation_state = "ACTIVE"

    _reset_active_timer(session)
    await process_user_turn(session, text, speaker_id=session.user_id, source="text")


async def handle_interrupt(session: Session, msg: dict):
    """Client-initiated interrupt (e.g. stop / pause)."""
    _ensure_services(session.websocket.app.state)
    action = msg.get("action", "stop")
    logger.info("Interrupt action=%s session=%s", action, session.session_id)
    await _interrupt_handler.handle(session, action)
    await send_status(session, "listening")


async def handle_playback_done(session: Session, msg: dict):
    """Client signals it finished playing the last audio segment."""
    logger.info("Playback done session=%s", session.session_id)
    session.playback_state = "IDLE"
    session.activation_state = "ACTIVE"
    _reset_active_timer(session)
    await send_status(session, "listening")


async def handle_mode_switch(session: Session, msg: dict):
    """Switch conversation mode (e.g. 'focus', 'casual', …)."""
    _ensure_services(session.websocket.app.state)
    new_mode = msg.get("mode", "default")
    logger.info("Mode switch session=%s mode=%s", session.session_id, new_mode)
    _mode_manager.switch(session, new_mode, trigger="client")
    await session.send({"type": "mode_changed", "mode": new_mode})


async def handle_speaker_label(session: Session, msg: dict):
    """Label / rename a speaker in the diarizer model."""
    _ensure_services(session.websocket.app.state)
    await _persona_agent.label_speaker(
        session,
        msg.get("speaker_id"),
        msg.get("name"),
    )


# ========================================================================= #
#  MESSAGE_HANDLERS dispatch table (populated now that functions exist)      #
# ========================================================================= #

MESSAGE_HANDLERS = {
    "wake":          handle_wake,
    "audio_chunk":   handle_audio_chunk,
    "text_input":    handle_text_input,
    "interrupt":     handle_interrupt,
    "playback_done": handle_playback_done,
    "mode_switch":   handle_mode_switch,
    "speaker_label": handle_speaker_label,
}


# ========================================================================= #
#  SHARED / UTILITY FUNCTIONS                                               #
# ========================================================================= #

async def send_status(session: Session, state: str):
    """Send a short status frame to the client."""
    logger.info("Status session=%s state=%s", session.session_id, state)
    await session.send({"type": "status", "state": state})


def _looks_like_url(text: str) -> bool:
    """Return True when the input looks like a pasted URL."""
    candidate = text.strip()
    return bool(_URL_PATTERN.search(candidate)) or ("://" in candidate and not candidate.startswith(" "))


def _extract_url_and_text(raw_text: str) -> tuple[str | None, str | None]:
    """Extract the first URL and any remaining text from a message."""
    match = _URL_PATTERN.search(raw_text.strip())
    if match is None:
        return None, None

    url = match.group(0).rstrip(".,;:!?)\"")
    before = raw_text[: match.start()].strip()
    after = raw_text[match.end() :].strip()
    remainder = " ".join(part for part in (before, after) if part).strip()
    return url, remainder or None


def _answer_from_recent_article(session: Session, text: str) -> str | None:
    """Return a deterministic answer for simple article follow-ups when possible."""
    reading_context = getattr(session, "last_read_context", None)
    if not isinstance(reading_context, dict):
        return None

    if not _AUTHOR_QUESTION_PATTERN.search(text):
        return None

    author = (reading_context.get("author") or "").strip()
    if not author:
        return None

    title = (reading_context.get("title") or "that article").strip()
    return f"The author of {title} is {author}."


def _extractive_summary(text: str, max_sentences: int = 3, max_chars: int = 900) -> str:
    """Create a short summary without relying on an LLM."""
    cleaned = re.sub(r"\s+", " ", text).strip()
    if not cleaned:
        return "I fetched the page, but there was no readable text to summarize."

    sentences = re.split(r"(?<=[.!?])\s+", cleaned)
    chosen: list[str] = []
    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue
        chosen.append(sentence)
        if len(chosen) >= max_sentences:
            break

    summary = " ".join(chosen) if chosen else cleaned[:max_chars]
    if len(summary) > max_chars:
        summary = summary[:max_chars].rstrip() + "..."
    return summary


async def _read_url_response(session: Session, url_text: str, question: str | None = None) -> str:
    """Read a pasted URL via the web_reader skill and return a short summary."""
    _ensure_services(session.websocket.app.state)

    if _skill_runner is None:
        raise RuntimeError("skill runner unavailable")

    logger.info("URL fast-path session=%s url=%s question=%r", session.session_id, url_text, question)
    result = await _skill_runner.execute(
        skill_id="web_reader",
        input_data={"url": url_text, "question": question or "Summarize this page"},
    )

    if not isinstance(result, dict) or not result.get("success"):
        error = result.get("error", "Unknown error") if isinstance(result, dict) else str(result)
        logger.warning("URL read failed session=%s error=%s", session.session_id, error)
        return f"I could not read that page: {error}"

    page_text = str(result.get("result", ""))
    metadata = result.get("metadata", {}) if isinstance(result, dict) else {}
    title = metadata.get("title") or "the page"
    summary = _extractive_summary(page_text)

    # Always store article context for follow-up questions
    session.last_read_context = {
        "url": metadata.get("url") or url_text,
        "title": title,
        "summary": summary,
        "excerpt": page_text[:12000],
    }

    if question:
        try:
            answer = await _orchestrator.llm_router.call(
                user_id=session.user_id,
                task_type="orchestrate",
                messages=[
                    {"role": "system", "content": "Answer the user's question from the article text. Be concise and factual."},
                    {"role": "user", "content": f"Article title: {title}\n\nArticle text:\n{page_text[:3000]}\n\nQuestion: {question}"},
                ],
                max_tokens=400,
            )
            _append_turn(session, "user", f"{url_text} {question}", speaker_id=session.user_id)
            _append_turn(session, "assistant", answer, speaker_id="assistant")
            return answer
        except Exception as exc:
            logger.warning("Question-on-URL answer failed session=%s: %s", session.session_id, exc)

    _append_turn(session, "user", url_text, speaker_id=session.user_id)
    _append_turn(
        session,
        "assistant",
        f"Here is a quick summary of {title}: {summary}",
        speaker_id="assistant",
    )

    return f"Here is a quick summary of {title}: {summary}"


async def process_user_turn(session: Session, text: str, speaker_id: str, source: str):
    """
    THE single processing path for all user input.
    Both voice and text converge here.
    """
    _ensure_services(session.websocket.app.state)
    logger.info(
        "process_user_turn session=%s source=%s speaker=%s preview=%r",
        session.session_id,
        source,
        speaker_id,
        text[:120],
    )

    if source == "text" and _looks_like_url(text):
        url, question = _extract_url_and_text(text)
        if url:
            logger.info("Detected URL input session=%s url=%r question=%r", session.session_id, url, question)
            response_body = await _read_url_response(session, url, question=question)
            session.activation_state = "SPEAKING"
            session.playback_state = "PLAYING"
            await stream_response(session, response_body)
            return

    recent_article_answer = _answer_from_recent_article(session, text)
    if recent_article_answer:
        _append_turn(session, "user", text, speaker_id=speaker_id)
        _append_turn(session, "assistant", recent_article_answer, speaker_id="assistant")
        session.activation_state = "SPEAKING"
        session.playback_state = "PLAYING"
        await stream_response(session, recent_article_answer)
        return

    # If a task is already running, queue this input and return
    task_state = getattr(session, "task_state", None) or {}
    if task_state.get("status") == "running":
        if not hasattr(session, "input_queue"):
            session.input_queue = []
        session.input_queue.append({"text": text, "speaker_id": speaker_id, "source": source})
        await send_status(session, "queued")
        return

    # Mark task as running
    if not hasattr(session, "task_state"):
        session.task_state = {}
    session.task_state["status"] = "running"

    try:
        # Append to working memory
        if hasattr(session, "working_memory"):
            _append_turn(session, "user", text, speaker_id=speaker_id)

        await send_status(session, "processing")

        # Build context and run orchestrator
        context = await _context_builder.build(session, text, speaker_id)
        result = await _orchestrator.run(session, context, text)
        logger.info("Orchestrator result session=%s type=%s", session.session_id, type(result).__name__)

        # Transition to speaking / playing state
        session.activation_state = "SPEAKING"
        session.playback_state = "PLAYING"

        # If the result carries an "ack" field, stream it first
        if isinstance(result, dict) and "ack" in result:
            await stream_response(session, result["ack"])
            response_body = result.get("response", result.get("text", ""))
        elif isinstance(result, dict):
            response_body = result.get("response", result.get("text", ""))
        else:
            response_body = result

        await stream_response(session, response_body)

        _append_turn(session, "assistant", str(response_body), speaker_id="assistant")

        # Background memory processing (fire-and-forget)
        asyncio.create_task(
            _memory_agent.process_turn(session, text, response_body)
        )
    finally:
        session.task_state["status"] = "idle"

    # Drain anything that arrived while we were busy
    await _drain_input_queue(session)


async def _drain_input_queue(session: Session):
    """
    Process queued inputs that arrived while a turn was running.
    - If ANY queued item is a cancel intent → discard entire queue.
    - Otherwise → process only the LAST item (most recent intent wins).
    """
    queue: list[dict] = getattr(session, "input_queue", None) or []
    if not queue:
        return

    # Snapshot and clear
    items = list(queue)
    queue.clear()

    # Check for cancellation intents
    for item in items:
        if item.get("text", "").strip().lower() in CANCEL_WORDS:
            logger.info("Cancel intent detected in queue — discarding %d item(s)", len(items))
            return

    # Only the most recent item matters
    last = items[-1]
    await process_user_turn(
        session,
        last["text"],
        last["speaker_id"],
        last["source"],
    )


async def stream_response(session: Session, response: Union[str, AsyncIterator[str]]):
    """
    Stream text + TTS audio to the client with 1-sentence lookahead.

    For each sentence:
      1. Await TTS for the *current* sentence (started last iteration).
      2. Kick off TTS for the *next* sentence in background.
      3. Send response_text + audio_chunk frames.
    Final frame: {"type":"response_text","text":"","is_final":True}
    """
    _ensure_services(session.websocket.app.state)

    # ---- Collect sentences ------------------------------------------------
    sentences: list[str] = []

    if isinstance(response, str):
        # Naive sentence splitter (period / ! / ? followed by space or EOL)
        import re
        raw_sentences = re.split(r'(?<=[.!?])\s+', response.strip())
        sentences = [s for s in raw_sentences if s.strip()]
    else:
        # AsyncIterator[str] — accumulate chunks and split on the fly
        buffer = ""
        import re
        async for chunk in response:
            buffer += chunk
            # Flush complete sentences as they form
            parts = re.split(r'(?<=[.!?])\s+', buffer)
            if len(parts) > 1:
                for part in parts[:-1]:
                    if part.strip():
                        sentences.append(part.strip())
                buffer = parts[-1]
        if buffer.strip():
            sentences.append(buffer.strip())

    if not sentences:
        await session.send({"type": "response_text", "text": "", "is_final": True})
        return

    # ---- Stream with 1-sentence TTS lookahead -----------------------------
    next_tts_task: asyncio.Task | None = None

    # Pre-start TTS for the first sentence
    next_tts_task = asyncio.create_task(
        asyncio.to_thread(_tts.synthesize, sentences[0])
    )

    for idx, sentence in enumerate(sentences):
        # Check for interruption
        if getattr(session, "activation_state", None) == "INTERRUPTED":
            if next_tts_task is not None:
                next_tts_task.cancel()
            break

        # Await TTS for current sentence
        pcm_samples, sample_rate = await next_tts_task

        # Start TTS for next sentence (lookahead) if available
        if idx + 1 < len(sentences):
            next_tts_task = asyncio.create_task(
                asyncio.to_thread(_tts.synthesize, sentences[idx + 1])
            )
        else:
            next_tts_task = None

        # Convert PCM to WAV and encode
        wav_bytes = pcm_to_wav(pcm_samples, sample_rate)
        audio_b64 = base64.b64encode(wav_bytes).decode("ascii")

        # Send text frame
        await session.send({
            "type": "response_text",
            "text": sentence,
            "is_final": False,
        })

        # Send audio frame
        await session.send({
            "type": "audio_chunk",
            "data": audio_b64,
        })

    # Final marker
    await session.send({"type": "response_text", "text": "", "is_final": True})
    # NOTE: caller owns activation_state / playback_state transitions


# ========================================================================= #
#  CONNECTION LIFECYCLE                                                     #
# ========================================================================= #

async def authenticate_connection(websocket: WebSocket) -> "Session | None":
    """
    Accept the WebSocket and wait for the first auth message.
    Returns a Session on success, None on failure (connection closed).
    """
    await websocket.accept()

    try:
        raw = await websocket.receive_json()
    except (WebSocketDisconnect, Exception):
        return None

    if not isinstance(raw, dict) or raw.get("type") != "auth":
        await websocket.send_json({"type": "auth_error", "reason": "expected auth message"})
        await websocket.close(code=4001)
        return None

    token = raw.get("token")
    if not token:
        await websocket.send_json({"type": "auth_error", "reason": "missing token"})
        await websocket.close(code=4001)
        return None

    user_id = validate_token(token)
    if user_id is None:
        await websocket.send_json({"type": "auth_error", "reason": "invalid token"})
        await websocket.close(code=4003)
        return None

    session = create_session(user_id, websocket)
    sqlite_store = getattr(websocket.app.state, "sqlite_store", None)
    if sqlite_store is not None:
        user = sqlite_store.get_user(user_id)
        if user is not None:
            session.enabled_mcps = list(getattr(user, "enabled_mcps", []) or [])
    active_sessions[session.session_id] = session

    await websocket.send_json({
        "type": "auth_ok",
        "user_id": user_id,
        "session_id": session.session_id,
    })

    logger.info("Authenticated user=%s session=%s", user_id, session.session_id)
    return session


async def message_loop(session: Session, websocket: WebSocket):
    """Receive messages in a loop and dispatch to the correct handler."""
    while True:
        try:
            msg = await websocket.receive_json()
        except WebSocketDisconnect:
            logger.info("Client disconnected (session=%s)", session.session_id)
            break
        except Exception as exc:
            logger.warning("Bad frame from session=%s: %s", session.session_id, exc)
            continue

        if not isinstance(msg, dict):
            logger.warning("Non-dict message from session=%s, ignoring", session.session_id)
            continue

        msg_type = msg.get("type")
        logger.debug("WS message session=%s type=%s", session.session_id, msg_type)
        handler = MESSAGE_HANDLERS.get(msg_type)

        if handler is None:
            logger.warning("Unknown message type '%s' from session=%s", msg_type, session.session_id)
            continue

        try:
            await handler(session, msg)
        except Exception as exc:
            logger.exception(
                "Error handling '%s' for session=%s: %s",
                msg_type,
                session.session_id,
                exc,
            )
            try:
                await session.send({
                    "type": "error",
                    "message": "I hit a problem processing that message. Please try again.",
                })
            except Exception:
                pass


async def cleanup_session(session: Session):
    """Guaranteed cleanup on disconnect."""
    logger.info("Cleaning up session=%s user=%s", session.session_id, session.user_id)
    # Cancel active window timer
    timer = getattr(session, "_active_timer", None)
    if timer is not None:
        timer.cancel()

    # Remove from session store
    active_sessions.pop(session.session_id, None)

    logger.info("Cleaned up session=%s user=%s", session.session_id, session.user_id)


async def websocket_endpoint(websocket: WebSocket):
    """
    THE single entry point for all WebSocket communication.
    Mounted at /ws/vayumi.
    """
    _ensure_services(websocket.app.state)

    session = await authenticate_connection(websocket)
    if session is None:
        return

    try:
        await message_loop(session, websocket)
    finally:
        await cleanup_session(session)