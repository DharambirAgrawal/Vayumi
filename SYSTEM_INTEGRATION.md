# Vayumi System Integration

This document is the primary architecture and integration reference for Vayumi runtime behavior.

## 1. System Scope
- Voice transport: websocket (`/ws/audio`, `/ws/hardware`)
- Typed chat: websocket when connected, HTTP fallback (`POST /chat`) when disconnected
- Authentication: JWT bearer for HTTP and websocket
- Session ownership: enforced by user id
- Wake-word flow: local wake detector first, STT only when wake/command window logic allows
- TTS output: server-side streamed PCM over websocket binary frames

## 2. Runtime Pipeline
1. Client connects websocket with auth token.
2. Server creates session and binds user ownership.
3. Client streams PCM audio chunks.
4. Server performs VAD segmentation and live wake-interrupt checks while AI is speaking.
5. If command is accepted, server runs agent response pipeline.
6. Server streams response text events and TTS PCM chunks.
7. Interrupt can cancel active response and reopen wake window.

## 3. Response Policies
Vayumi supports response start policies internally:
- `replace`: cancel active response and start new one immediately
- `queue`: keep active response and enqueue new response

Current usage:
- Wake/voice command path: `replace`
- Interrupt/resume/speak control paths: `replace`
- Chat path (`chatbot_message` and websocket-routed `POST /chat`): `queue` by default

This avoids typed chat unexpectedly interrupting active spoken responses.

## 4. Interrupt Model
### 4.1 Interrupt Sources
- Explicit websocket `interrupt` control message
- Live wake detection during AI speech (low-latency chunk-level checks)

### 4.2 Interrupt Semantics
On interrupt:
- active response task is cancelled
- TTS stream state is reset
- resumable content is captured according to resume policy
- `interrupt_ack` event is emitted

### 4.3 Resume Policies
- `restart_sentence`
- `continue_token_stream`
- `continue_checkpoint`

## 5. Self-Echo and Overlap Guards
- Short-segment suppression (`MIN_TRANSCRIBE_SEGMENT_MS`)
- Self-echo suppression window after AI speaking (`SELF_ECHO_SUPPRESSION_SECONDS`)
- Wake-only interrupt confidence gating (`WAKE_INTERRUPT_MIN_CONFIDENCE`)
- Minimum command gap (`MIN_COMMAND_GAP_SECONDS`)
- Optional single-command wake mode (`WAKE_SINGLE_COMMAND_MODE`)

These reduce accidental follow-up commands from room noise or TTS feedback.

## 6. Wake Window Behavior
- Wake detection opens command window
- In single-command mode, window closes immediately after one accepted command
- Otherwise command window remains open until timeout

## 7. Client Audio Playback Expectations
- Client must set websocket `binaryType = arraybuffer`
- Client must decode streamed PCM16 chunks and schedule playback
- On interrupt, client should stop queued playback sources and drop stale chunks until next `tts_stream_start`

## 8. Memory/Orchestrator Integration Guidance
- Treat Vayumi as transport + interruption control plane
- Let orchestrator decide task-level continuation/flush behavior after interrupt
- Provide orchestrator with runtime state:
  - `is_ai_speaking`
  - active response id
  - queue size
  - resume policy
  - last wake status
- Persist long-term conversation state in memory system, not in transport/session internals

## 9. Environment Knobs (High Impact)
- `WAKE_DETECTOR_PROVIDER`
- `WAKE_DETECTOR_MODEL_PATH`
- `WAKE_INTERRUPT_MIN_CONFIDENCE`
- `VAD_RMS_THRESHOLD`
- `MIN_TRANSCRIBE_SEGMENT_MS`
- `SELF_ECHO_SUPPRESSION_SECONDS`
- `LIVE_INTERRUPT_CHECK_MS`
- `LIVE_INTERRUPT_BUFFER_MS`
- `KOKORO_VOICE`

## 10. Canonical Usage Rule
- Wake/voice controls interruption.
- Chat should not interrupt by default.
- Agent/orchestrator can explicitly choose interruption policy when needed.

## 11. How To Pass Runtime Intent
For every request, orchestrator should explicitly set:
- `respond_via`: `chat_only`, `voice_and_chat`, or `voice_only`
- `interrupt_policy`: `queue` or `replace`

Recommended defaults:
- typed UI chat: `respond_via=chat_only`, `interrupt_policy=queue`
- wake/voice commands: `respond_via=voice_and_chat`, `interrupt_policy=replace`
- urgent system alerts: `respond_via=voice_and_chat`, `interrupt_policy=replace`

## 12. Queue and Flush Timeline
If response A is active and response B arrives:
- B with `queue`: A continues, B waits, B starts after A ends.
- B with `replace`: A is cancelled, TTS for A is cancelled, B starts now.

If an interrupt occurs during A:
- A is flushed
- server emits `interrupt_ack` with flushed response id and resumable token count
- orchestration can call resume endpoint or send a fresh request

## 13. Notes For Agent Builders
- Do not rely on implicit defaults if behavior matters; pass both fields explicitly.
- Treat `interrupt_ack` as a state transition signal, not only a UI message.
- Keep memory decisions in orchestrator/memory layer; transport layer enforces timing and cancellation only.

## 14. Meeting Mode Pipeline
Meeting mode is optimized for low-latency transcript capture rather than conversational replies.

Pipeline in meeting mode:
1. VAD finalizes an audio segment.
2. Server accumulates audio until `MEETING_MIN_TRANSCRIBE_SEGMENT_MS`.
3. STT transcribes the accumulated segment.
3. Diarization engine emits timestamped speaker segment(s).
4. Server sends `diarization_segment` event(s).
5. Server sends `transcription_final` with mode/timestamp metadata.

Expected outcome:
- continuous meeting transcript with speaker labels and timestamps
- no auto-TTS chatter for every meeting segment
- orchestration layer decides when to summarize or respond

Provider note:
- Meeting mode uses the same STT provider configured for runtime (`STT_PROVIDER`, default Groq Whisper API).
- Wake-word local detector remains separate and is only for wake gating in conversation flow.

## 15. Runtime Function Map (Server Internals)
Primary runtime functions are implemented in `server/main.py`.

Session and protocol lifecycle:
- `_run_websocket_session(websocket, client_type)`
  - validates auth
  - sends `hello`
  - requires `client_ready`
  - starts message loop for binary audio and text control messages
- `_create_session_for_websocket(client_type, websocket, user)`
  - creates session
  - binds `session.user_id`
  - emits `hello` capabilities payload

Message routing:
- `_handle_audio_message(session_id, message, websocket, session)`
  - handles: `audio_stream_start`, `audio_stream_end`, `interrupt`, `ping`
- `_handle_control_message(session_id, message, websocket, session)`
  - handles: `mode_switch`, `chatbot_message`, `resume_response`, `set_resume_policy`

Response execution and interrupt control:
- `_start_agent_response_with_policy(websocket, session, transcript, respond_via, interrupt_policy)`
  - `interrupt_policy=queue`: enqueue
  - `interrupt_policy=replace`: cancel active and start now
- `_run_agent_response(websocket, session, transcript, respond_via, generation)`
  - emits agent text lifecycle events and optional TTS
- `_interrupt_active_response(websocket, session, trigger)`
  - central interrupt handler
  - emits `interrupt_ack`
- `_stream_tts_audio(websocket, session, text, response_id, generation)`
  - emits `tts_stream_start`, binary PCM chunks, `tts_stream_end`

Wake/VAD/STT and meeting handling:
- `_maybe_detect_live_wake_interrupt(websocket, session, session_id, chunk)`
- `_handle_speech_segment(websocket, session, session_id)`
- `_finalize_transcription(websocket, session, transcript, response_id, respond_via)`
- `_finalize_meeting_transcription(websocket, session, transcript, diarization_segments)`

## 16. Integration Tools and Parameters
In this document, "tools" means runtime calls you can make from client/orchestrator.

HTTP tools:
- `POST /chat`
  - body:
    - `text: string` (required)
    - `respond_via: "chat_only" | "voice_and_chat" | "voice_only"` (optional, default `chat_only`)
    - `interrupt_policy: "queue" | "replace"` (optional, default `queue`)
    - `session_id: string` (optional; if active websocket exists for this session, request is routed into websocket runtime)
- `POST /session/{session_id}/resume-policy`
  - body:
    - `policy: "restart_sentence" | "continue_token_stream" | "continue_checkpoint"`
- `POST /session/{session_id}/resume`
  - resumes interrupted response if resumable tokens exist
- `POST /session/{session_id}/speak`
  - deterministic speech trigger using normal response pipeline
- `GET /session/{session_id}/status`
  - returns runtime state such as `mode`, `is_ai_speaking`, `tts_active`, `meeting_timeline_ms`

WebSocket tools (inbound text messages):
- `client_ready`
  - payload:
    - `type: "client_ready"`
    - `client_type: "web" | "hardware"`
    - `capabilities: string[]`
    - `audio_config: { sample_rate?: number, channels?: number, bit_depth?: number }`
- `mode_switch`
  - payload:
    - `type: "mode_switch"`
    - `mode: "conversation" | "meeting"`
- `chatbot_message`
  - payload:
    - `type: "chatbot_message"`
    - `text: string` (required)
    - `respond_via?: "chat_only" | "voice_and_chat" | "voice_only"` (default `chat_only`)
    - `interrupt_policy?: "queue" | "replace"` (default `queue`)
- `interrupt`
  - payload:
    - `type: "interrupt"`
    - `trigger?: string` (example: `"user_click"`)
- `resume_response`
  - payload: `{ "type": "resume_response" }`
- `set_resume_policy`
  - payload:
    - `type: "set_resume_policy"`
    - `policy: "restart_sentence" | "continue_token_stream" | "continue_checkpoint"`
- `audio_stream_start` / `audio_stream_end` / `ping`
  - control markers for client audio lifecycle and keepalive

Binary websocket tool:
- binary frames on `/ws/audio` or `/ws/hardware`
  - expected format: PCM16 mono chunks (client-defined chunking)

## 17. Meeting vs Conversation: What Actually Happens
Conversation mode (`mode=conversation`):
- Wake-word gating is active for voice command acceptance.
- After STT finalization, server may start agent response flow.
- Agent response can emit:
  - `agent_thinking`
  - `agent_response_start`
  - `agent_response_chunk` (streamed text)
  - `chatbot_response` (final text summary)
  - optional TTS stream (`tts_stream_start`, binary PCM, `tts_stream_end`) when `respond_via != chat_only`

Meeting mode (`mode=meeting`):
- `session.meeting_timeline_ms` and meeting segment buffer are reset on switch.
- audio accumulates until `MEETING_MIN_TRANSCRIBE_SEGMENT_MS` threshold.
- server emits diarization and transcript events for note-taking:
  - `diarization_segment`
  - `transcription_final` with meeting timestamps/metadata
- no automatic conversational TTS chatter for every segment.

## 18. Mode Switch Sequences
Switch to meeting mode (recommended):
1. Send websocket message:
   - `{ "type": "mode_switch", "mode": "meeting" }`
2. Wait for `mode_changed` ack.
3. Verify in ack:
   - `mode = "meeting"`
   - `features.diarization = true`
4. Continue streaming audio chunks.
5. Consume `diarization_segment` and `transcription_final` events.

Switch back to conversation mode:
1. Send websocket message:
   - `{ "type": "mode_switch", "mode": "conversation" }`
2. Wait for `mode_changed` ack.
3. Verify in ack:
   - `mode = "conversation"`
   - `features.diarization = false`
4. Resume normal conversation commands:
   - wake + voice command, or
   - `chatbot_message` / `POST /chat`.

## 19. Canonical Payload Examples
Typed chat that does not interrupt speech:
```json
{
  "type": "chatbot_message",
  "text": "Summarize the last point",
  "respond_via": "chat_only",
  "interrupt_policy": "queue"
}
```

Voice-priority command that should preempt:
```json
{
  "type": "chatbot_message",
  "text": "Stop and read this urgent alert",
  "respond_via": "voice_and_chat",
  "interrupt_policy": "replace"
}
```

Set resume policy:
```json
{
  "type": "set_resume_policy",
  "policy": "continue_checkpoint"
}
```

Interrupt current response:
```json
{
  "type": "interrupt",
  "trigger": "user_click"
}
```

## 20. Minimal Client Implementation Checklist
- Set websocket `binaryType = "arraybuffer"`.
- After connect, always send `client_ready` before other commands.
- On mode switch, wait for `mode_changed` before assuming new behavior.
- For meeting mode UI, subscribe to `diarization_segment` and `transcription_final`.
- For conversation mode UI, subscribe to agent and TTS lifecycle events.
- On interrupt:
  - stop local playback queue
  - drop stale PCM until next `tts_stream_start`
  - treat `interrupt_ack` as authoritative state transition.
