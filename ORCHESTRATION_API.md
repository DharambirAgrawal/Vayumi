# Vayumi Orchestration API and Tool Surface

This document is the canonical function/event surface for integrating Vayumi with orchestration and memory systems.

## 1. HTTP Endpoints

### Auth
- `POST /auth/register`
- `POST /auth/login`
- `GET /auth/me`

### Health/Session
- `GET /health`
- `GET /session/{session_id}/status`

### Chat and Runtime Controls
- `POST /chat`
  - key fields: `text`, `respond_via`, `session_id`, `interrupt_policy`
  - `interrupt_policy`: `queue` or `replace`
- `POST /session/{session_id}/resume-policy`
- `POST /session/{session_id}/resume`
- `POST /session/{session_id}/speak`

## 2. WebSocket Endpoints
- `WS /ws/audio`
- `WS /ws/hardware`

Auth token required (query param or bearer header).

## 3. WebSocket Inbound Control Messages
- `client_ready`
- `mode_switch`
- `chatbot_message`
  - supports `respond_via`
  - supports `interrupt_policy` (`queue` by default)
  - supports `attachments` and attachment-aware link/image/audio/video context
- `interrupt`
- `resume_response`
- `set_resume_policy`
- `audio_stream_start`
- `audio_stream_end`
- `ping`

## 4. WebSocket Outbound Events
### Session/Mode
- `hello`
- `session_started`
- `mode_changed`

### Wake/VAD/STT
- `wake_word_detected`
- `wake_word_status`
- `wake_word_required`
- `wake_word_debug`
- `wake_window_opened`
- `wake_window_closed`
- `vad_speech_start`
- `vad_speech_end`
- `transcription_partial`
- `transcription_final`
- `speaker_identified`

### Agent/TTS
- `agent_thinking`
- `agent_response_start`
- `agent_response_chunk`
- `agent_response_end`
- `chatbot_response`
- `tts_stream_start`
- `tts_stream_end`
- websocket binary PCM chunks for TTS stream

### Interrupt/Errors
- `interrupt_ack`
- `resume_policy_changed`
- `error`
- `pong`

## 5. Runtime Server Functions (Internal)
- `_start_agent_response_with_policy(...)`
  - supports `interrupt_policy` = `replace` or `queue`
- `_interrupt_active_response(...)`
  - centralized cancel/resume-state capture
- `_maybe_detect_live_wake_interrupt(...)`
  - low-latency interrupt detection while speaking
- `_handle_speech_segment(...)`
  - segment gating + wake/STT route control
- `_finalize_transcription(...)`
  - wake window + command acceptance logic

## 6. AI/Orchestrator Control Capabilities
Agent or orchestrator can control:
- interrupt current speech
- queue or replace new responses
- set resume policy
- trigger deterministic speech (`/speak`)
- resume interrupted response (`/resume`)
- mode switching and runtime state inspection

## 7. Memory System Integration Contract
Recommended minimal contract between orchestrator and memory:
- input: user utterance, wake status, interruption metadata, response id
- output: response text, response policy (`queue`/`replace`), optional resume strategy
- persistence: store semantic conversation state in memory system, not websocket session internals

Default local persistence layout:
- SQLite index DB: `data/memory/memory.db`
- Blob assets: `data/memory/blobs/`
- All memory categories are stored in the same DB table and distinguished by memory `type`.

## 8. Link and Attachment Reading Contract
The assistant can read and summarize links and attachments through the instruction-aware `read_url` tool.

Recommended call pattern:

```json
{
  "url": "https://example.com/article",
  "instruction": "summarize in 3 bullets and call out any risks",
  "prefer_dynamic": true,
  "max_chars": 8000
}
```

Behavior:
- the tool first tries a lightweight scraper path
- it falls back to HTML fetch + cleanup when the page is static
- it returns structured JSON with `fetchable`, `status`, `fetch_method`, `summary`, and `clean_text`
- protected, blocked, or empty pages return a structured failure payload instead of crashing the turn
- sub-agents in the `research` bundle may use `read_url` directly for instruction-driven link digestion

## 9. Integration Defaults
- Voice/wake path: `replace`
- Typed chat path: `queue`
- Interrupt trigger: wake-word or explicit control

These defaults provide stable conversational behavior with low overlap risk.

## 10. Queue vs Flush Semantics
Use these rules as the canonical runtime contract.

- `interrupt_policy=queue`:
  - if AI is already responding, new request is appended to session queue
  - active response continues
  - queued item starts automatically after `agent_response_end`
- `interrupt_policy=replace`:
  - active response task is cancelled immediately
  - current TTS stream is cancelled
  - new request starts immediately

Interrupt behavior (`interrupt` control or wake barge-in):
- server emits `interrupt_ack`
- payload includes:
  - `flushed_response_id`: response that was cancelled
  - `resume_policy`: active resume policy at cancellation time
  - `resumable_tokens`: token count available for `/session/{id}/resume`

## 11. Canonical Message Payloads

Typed chat over websocket (non-interrupting, text-first):

```json
{
  "type": "chatbot_message",
  "text": "Summarize last standup in 3 bullets",
  "respond_via": "chat_only",
  "interrupt_policy": "queue"
}
```

Voice-priority action over websocket (preemptive):

```json
{
  "type": "chatbot_message",
  "text": "Stop current output and read the alert now",
  "respond_via": "voice_and_chat",
  "interrupt_policy": "replace"
}
```

Typed chat over HTTP fallback:

```json
{
  "text": "Give me deployment status",
  "respond_via": "chat_only",
  "interrupt_policy": "queue",
  "session_id": "<optional-active-session-id>"
}
```

Explicit interrupt command:

```json
{
  "type": "interrupt",
  "trigger": "user_click"
}
```

## 12. Meeting Mode Behavior (Current)
- `mode_switch` to `meeting` enables timestamped diarization event flow.
- In meeting mode, audio segments are transcribed and emitted as `diarization_segment` events with:
  - `speaker`
  - `text`
  - `start_ms`
  - `end_ms`
  - `confidence`
- `transcription_final` is still emitted and includes meeting timestamps.
- Voice wake-command agent response flow is not auto-triggered per segment in meeting mode.
- Integrators should use these meeting segments to build notes, summaries, and action items.
- Meeting-mode STT uses the same configured STT provider as conversation mode (default: Groq Whisper API).
- Meeting mode batches audio before STT using `MEETING_MIN_TRANSCRIBE_SEGMENT_MS` (default `6000`) to reduce request churn.

## 13. Mode Switching Contract
Switch to meeting mode:

```json
{
  "type": "mode_switch",
  "mode": "meeting"
}
```

Switch back to conversation mode:

```json
{
  "type": "mode_switch",
  "mode": "conversation"
}
```

Server acknowledgment:
- `mode_changed` with `features` object
- in meeting mode, server resets meeting timeline/segments for the new meeting run
