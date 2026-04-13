# Vayumi — AI Agent Voice Platform
## Phase 1: WebSocket Layer + React Client

> **Scope of this document:** The real-time WebSocket communication layer between the React web client and the Python backend server. Includes all state machines, audio pipeline, client-exposed functions, server-exposed functions, and what the AI agent itself can control at runtime.

---

## 1. System Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                        VAYUMI PLATFORM                          │
│                                                                 │
│   ┌──────────────────┐          ┌──────────────────────────┐   │
│   │   React Client   │◄────────►│    Python Server         │   │
│   │  (Browser / PWA) │ WebSocket│  (FastAPI + asyncio)     │   │
│   │                  │          │                          │   │
│   │ • Wake word (JS) │          │ • VAD (server-side)      │   │
│   │ • VAD (browser)  │          │ • Diarization            │   │
│   │ • Audio capture  │          │ • AI Agent core          │   │
│   │ • Chatbot UI     │          │ • TTS / STT              │   │
│   │ • Mode switcher  │          │ • Tool execution         │   │
│   └──────────────────┘          └──────────────────────────┘   │
│                                                                 │
│   ┌──────────────────┐                                         │
│   │   ESP32-S3       │──────────────────────────────────────►  │
│   │  (Hardware)      │ WebSocket (raw audio, no VAD/wake)      │
│   └──────────────────┘                                         │
│                                                                 │
│         One active connection at a time (Web OR Hardware)       │
└─────────────────────────────────────────────────────────────────┘
```

**Key design rule:** Only ONE primary client is connected and active as the voice source at any time. However the chatbot panel on the web client remains usable even when the hardware is the active voice source, and the AI's response can be routed back through the hardware speaker.

---

## 2. Architecture Decisions

| Decision | Choice | Reason |
|---|---|---|
| Transport | WebSocket (binary + JSON frames) | Ultra-low latency, full-duplex, browser-native |
| Audio format | 16-bit PCM, 16kHz mono, chunked | Universal STT compatibility, low overhead |
| Wake word (web) | Browser JS (Porcupine or custom WASM) | Saves server CPU; ESP32 can't run it |
| VAD (web) | Browser JS (Silero WASM or WebRTC VAD) | Stop streaming silence; reduce bandwidth |
| VAD (ESP32) | Server-side | ESP32 S3 too constrained |
| Backend | Python FastAPI + `websockets` | Async-first, fast, easy AI integration |
| Session state | Server holds canonical state | Single source of truth |
| Interruption | Client signals → server queues/flushes | Prevents echo feedback loops |

---

## 3. Connection & Session Lifecycle

### 3.1 Handshake Protocol

When the user clicks **Connect** on the web client (or the ESP32 powers on), this sequence happens:

```
Client                                  Server
  │                                        │
  │── WS Connect (ws://host/ws/audio) ────►│
  │                                        │
  │◄─ { type: "hello",                     │
  │     session_id: "abc123",              │
  │     server_version: "1.0",             │
  │     client_type_accepted: "web",       │
  │     modes: ["conversation","meeting"], │
  │     wake_word: "vayumi" }  ────────────│
  │                                        │
  │── { type: "client_ready",              │
  │     client_type: "web",               │
  │     capabilities: ["vad","wake_word"], │
  │     audio_config: {                    │
  │       sample_rate: 16000,             │
  │       channels: 1,                    │
  │       bit_depth: 16 } } ─────────────►│
  │                                        │
  │◄─ { type: "session_started",          │
  │     session_id: "abc123",             │
  │     active: true } ────────────────────│
  │                                        │
```

### 3.2 Connection States (Client)

```
DISCONNECTED
    │
    │ [User clicks Connect button]
    ▼
CONNECTING
    │
    │ [WS open + hello received]
    ▼
CONNECTED_IDLE          ◄──────────────────────────┐
    │                                               │
    │ [Wake word detected]                          │
    ▼                                               │
WAKE_DETECTED                                       │
    │                                               │
    │ [VAD: speech started]                         │
    ▼                                               │
STREAMING_AUDIO ──────────────────────────────────►│
    │                                               │
    │ [VAD: silence / user stops]                   │
    ▼                                               │
WAITING_RESPONSE                                    │
    │                                               │
    │ [Server: AI starts speaking]                  │
    ▼                                               │
AI_SPEAKING ────────────────[silence/done]──────────┘
    │
    │ [Wake word "vayumi" detected mid-speech]
    ▼
INTERRUPTING ──► sends interrupt signal ──► back to WAKE_DETECTED
```

### 3.3 Disconnection & Reconnect

- Client always attempts auto-reconnect with exponential backoff (1s → 2s → 4s → max 30s)
- Server holds session state for 60 seconds after disconnect (configurable) so reconnect resumes context
- On clean disconnect (user clicks Disconnect), server flushes session immediately

---

## 4. WebSocket Message Protocol

All messages are JSON except audio chunks which are **binary frames**.

### 4.1 Frame Types

```
TEXT FRAME  →  JSON control/event messages
BINARY FRAME → Raw PCM audio (client→server) OR TTS audio (server→client)
```

### 4.2 Client → Server Messages

#### Audio stream start
```json
{
  "type": "audio_stream_start",
  "trigger": "wake_word",        // "wake_word" | "manual" | "meeting_mode"
  "timestamp": 1712345678.123
}
```

#### Audio chunk (binary frame)
```
[BINARY] Raw 16-bit PCM, 16kHz mono
Chunk size: 20ms = 320 samples = 640 bytes
```

#### Audio stream end
```json
{
  "type": "audio_stream_end",
  "reason": "vad_silence",       // "vad_silence" | "manual" | "timeout"
  "duration_ms": 3200
}
```

#### Interrupt signal
```json
{
  "type": "interrupt",
  "trigger": "wake_word",        // "wake_word" | "user_button"
  "timestamp": 1712345678.456,
  "wake_confidence": 0.94        // optional, from wake word engine
}
```

#### Mode switch request
```json
{
  "type": "mode_switch",
  "mode": "meeting",             // "conversation" | "meeting"
  "requested_by": "user_voice"   // "user_voice" | "ui_button"
}
```

#### Chatbot message (text/link/image/voice)
```json
{
  "type": "chatbot_message",
  "content_type": "text",        // "text" | "link" | "image" | "voice"
  "text": "What is in this image?",
  "attachments": [
    {
      "type": "image",
      "data": "<base64>",        // or "url": "https://..."
      "mime_type": "image/jpeg"
    }
  ],
  "respond_via": "voice_and_chat"  // "voice_and_chat" | "chat_only" | "voice_only"
}
```

#### Ping (keepalive)
```json
{ "type": "ping", "ts": 1712345678.000 }
```

---

### 4.3 Server → Client Messages

#### Session events
```json
{ "type": "session_started", "session_id": "abc123", "active": true }
{ "type": "session_ended", "reason": "user_disconnect" }
```

#### Speech events
```json
{ "type": "vad_speech_start" }
{ "type": "vad_speech_end" }

{ "type": "transcription_partial", "text": "what is the weat" }
{ "type": "transcription_final",   "text": "what is the weather today", "confidence": 0.97 }
```

#### AI Agent events
```json
{ "type": "agent_thinking" }

{
  "type": "agent_response_start",
  "response_id": "resp_001",
  "text": "The weather in Chennai today is..."
}

{ "type": "agent_response_end", "response_id": "resp_001" }

{
  "type": "agent_tool_call",
  "tool": "get_weather",
  "args": { "city": "Chennai" },
  "status": "running"            // "running" | "done" | "failed"
}
```

#### TTS audio (binary frames)
```
[BINARY] Raw PCM or Opus-encoded audio of AI's voice response
Preceded by:  { "type": "tts_stream_start", "response_id": "resp_001", "format": "pcm_16k" }
Followed by:  { "type": "tts_stream_end",   "response_id": "resp_001" }
```

#### Interrupt acknowledgement
```json
{
  "type": "interrupt_ack",
  "flushed_response_id": "resp_001",
  "queued_chars_dropped": 142
}
```

#### Mode events
```json
{
  "type": "mode_changed",
  "mode": "meeting",
  "features": {
    "diarization": true,
    "vad_sensitivity": "high",
    "wake_word_in_meeting": true
  }
}
```

#### Diarization events (meeting mode only)
```json
{
  "type": "diarization_segment",
  "speaker": "Speaker_1",
  "text": "I think we should move the deadline",
  "start_ms": 12400,
  "end_ms": 15800
}
```

#### Chatbot response
```json
{
  "type": "chatbot_response",
  "text": "The image shows a whiteboard with...",
  "spoken": true,                // whether it was also sent to TTS
  "response_id": "resp_002"
}
```

#### Pong
```json
{ "type": "pong", "ts": 1712345678.000, "server_ts": 1712345678.001 }
```

#### Error
```json
{
  "type": "error",
  "code": "audio_decode_failed",
  "message": "Could not decode PCM chunk",
  "fatal": false
}
```

---

## 5. Audio Pipeline

### 5.1 Web Client Audio Pipeline

```
Microphone (getUserMedia)
    │
    ▼
AudioWorklet (runs in audio thread)
    │  raw 32-bit float samples
    ▼
Resampler → 16kHz
    │
    ▼
16-bit PCM converter
    │
    ├──► Wake Word Engine (Porcupine WASM / custom)
    │         │ "vayumi" detected?
    │         ▼
    │    trigger: audio_stream_start
    │         │
    │         ▼
    └──► VAD (Silero WASM / WebRTC VAD)
              │ speech? → chunk to server
              │ silence? → audio_stream_end
              ▼
         WebSocket binary frames → Server
```

**Why AudioWorklet and not ScriptProcessor?**
ScriptProcessor runs on the main thread and causes dropouts under UI load. AudioWorklet runs on a dedicated audio thread — no dropouts even during heavy React renders.

### 5.2 ESP32-S3 Audio Pipeline (for reference)

```
I2S Microphone (INMP441)
    │ 32-bit, 44.1kHz
    ▼
Downsample → 16kHz (on-chip DSP)
    │
    ▼
16-bit PCM
    │
    ▼  (NO wake word, NO VAD — server handles both)
WebSocket binary frames → Server
```

Server applies VAD server-side for ESP32 connections. Wake word is also detected server-side for ESP32.

### 5.3 Server Audio Pipeline

```
WebSocket binary frames
    │
    ▼
Jitter buffer (50ms)
    │
    ├──[if ESP32]──► VAD (py-webrtcvad or Silero)
    │                     │ speech start/end events
    │
    ├──[if ESP32]──► Wake word detector (OpenWakeWord)
    │
    ▼
STT Engine (Whisper / Deepgram streaming)
    │  partial + final transcriptions
    ▼
AI Agent (LangChain / custom)
    │  tool calls, reasoning
    ▼
TTS Engine (ElevenLabs / Coqui / Piper)
    │  PCM audio chunks
    ▼
WebSocket binary frames → Client
```

---

## 6. Interruption Handling

This is the trickiest part. Here is the full flow:

```
AI is speaking  (server streaming TTS audio to client)
    │
    │  User says "Vayumi"
    │
    ▼
Client wake word engine fires
    │
    ├──► Client immediately MUTES the audio playback (stops playing TTS)
    │
    ├──► Client sends: { "type": "interrupt", "trigger": "wake_word" }
    │
    │                              Server receives interrupt
    │                                    │
    │                                    ├──► Cancels TTS generation
    │                                    ├──► Drops queued audio frames
    │                                    ├──► Cancels any pending tool calls (if safe)
    │                                    ├──► Sends: { "type": "interrupt_ack", ... }
    │                                    ├──► Sends: { "type": "vad_speech_start" }
    │                                    └──► Begins listening for new audio
    │
    ◄── interrupt_ack received
    │
    └──► Client starts streaming new audio immediately
```

**Echo prevention:** When AI is speaking through speakers and the microphone picks it up, the wake word engine must NOT fire on the AI's own voice saying a word that sounds like "vayumi". Mitigations:

- Acoustic Echo Cancellation (AEC) via browser's `echoCancellation: true` on getUserMedia
- On server: short lock-out window (200ms) after TTS stream starts, ignore wake events
- Wake word confidence threshold raised to 0.90+ during AI speech

---

## 7. Multi-Client Routing Logic

```
┌──────────────────────────────────────────────────────────┐
│                    SERVER SESSION MANAGER                │
│                                                          │
│  active_voice_source: "web" | "hardware" | null         │
│                                                          │
│  ┌─────────────────┐      ┌────────────────────────┐    │
│  │  Web Client     │      │  ESP32 Client          │    │
│  │  connected: T   │      │  connected: T          │    │
│  │  voice: ACTIVE  │      │  voice: STANDBY        │    │
│  │  chat: ACTIVE   │      │  voice: can't activate │    │
│  └─────────────────┘      └────────────────────────┘    │
│                                                          │
│  Web is voice source:                                    │
│  → Chatbot also active (web only, no conflict)          │
│                                                          │
│  Hardware is voice source:                               │
│  → Web chatbot still active                             │
│  → AI voice responses go → Hardware speaker             │
│  → Chatbot text responses also shown on web              │
└──────────────────────────────────────────────────────────┘
```

**Conflict rules:**

| Web connected | Hardware connected | Voice source | Chatbot |
|---|---|---|---|
| Yes | No | Web | Web |
| No | Yes | Hardware | — |
| Yes | Yes | Hardware (priority) | Web chatbot active, responses via HW speaker |
| Yes | Yes | Web forced | User explicitly switched; HW goes standby |

---

## 8. Modes

### 8.1 Conversation Mode (default)

- Standard VAD sensitivity
- Single speaker assumed
- Wake word: "Vayumi" to start each exchange
- TTS: normal latency target (< 800ms first chunk)

### 8.2 Meeting Mode

Activated by: user says "switch to meeting mode" OR UI button

- **Diarization ON** — speaker-labeled transcription segments streamed in real time
- **Elevated VAD sensitivity** — catches soft speech, side conversations
- **Continuous listening** — no wake word needed to transcribe (passive recording)
- **Wake word still active** — "Vayumi" still interrupts and takes a command
- **Output** — running transcript shown in UI + saved to session
- **Exit** — user says "Vayumi, end meeting" OR UI button

---

## 9. Functions Exposed by the Client

These are callable from within your app code — they wrap the WebSocket protocol cleanly.

### 9.1 Connection Management

```typescript
VayumiClient.connect(serverUrl: string, options?: ConnectOptions): Promise<void>
// Opens WS, sends client_ready, waits for session_started

VayumiClient.disconnect(reason?: string): void
// Graceful close, sends disconnect event

VayumiClient.getConnectionState(): ConnectionState
// "disconnected" | "connecting" | "connected_idle" | "streaming" | "ai_speaking"

VayumiClient.onStateChange(cb: (state: ConnectionState) => void): Unsubscribe
```

### 9.2 Audio Control

```typescript
VayumiClient.startMicrophone(): Promise<void>
// Requests mic permission, starts AudioWorklet pipeline

VayumiClient.stopMicrophone(): void

VayumiClient.setWakeWordEnabled(enabled: boolean): void
// Toggle wake word detection (e.g. disable in chatbot-only mode)

VayumiClient.setVADEnabled(enabled: boolean): void

VayumiClient.triggerManualPushToTalk(): void
// Bypass wake word, start streaming immediately (push-to-talk button)

VayumiClient.releaseManualPushToTalk(): void
```

### 9.3 Interrupt

```typescript
VayumiClient.interrupt(): void
// Sends interrupt signal, mutes local playback immediately
// Use when wake word fires mid-AI-speech
```

### 9.4 Mode Switching

```typescript
VayumiClient.switchMode(mode: 'conversation' | 'meeting'): Promise<void>
// Sends mode_switch, waits for mode_changed ack

VayumiClient.getCurrentMode(): 'conversation' | 'meeting'
```

### 9.5 Chatbot

```typescript
VayumiClient.sendChatMessage(message: ChatMessage): Promise<void>
// message: { text?, attachments?: Attachment[], respondVia: 'voice_and_chat' | 'chat_only' | 'voice_only' }

VayumiClient.onChatResponse(cb: (response: ChatResponse) => void): Unsubscribe
```

### 9.6 Event Subscriptions

```typescript
VayumiClient.on('wake_word_detected', cb: (confidence: number) => void)
VayumiClient.on('vad_speech_start', cb: () => void)
VayumiClient.on('vad_speech_end', cb: () => void)
VayumiClient.on('transcription_partial', cb: (text: string) => void)
VayumiClient.on('transcription_final', cb: (text: string, confidence: number) => void)
VayumiClient.on('agent_thinking', cb: () => void)
VayumiClient.on('agent_speaking', cb: (responseId: string) => void)
VayumiClient.on('agent_done', cb: (responseId: string) => void)
VayumiClient.on('interrupt_ack', cb: (info: InterruptAck) => void)
VayumiClient.on('mode_changed', cb: (mode: Mode, features: ModeFeatures) => void)
VayumiClient.on('diarization_segment', cb: (segment: DiarizationSegment) => void)
VayumiClient.on('error', cb: (error: VayumiError) => void)
```

---

## 10. Functions Exposed by the Server

These are Python async functions/endpoints your server provides.

### 10.1 WebSocket Handler

```python
@app.websocket("/ws/audio")
async def audio_websocket(websocket: WebSocket):
    # Handles the full client lifecycle

@app.websocket("/ws/hardware")
async def hardware_websocket(websocket: WebSocket):
    # Dedicated endpoint for ESP32 — no wake word, server-side VAD
```

### 10.2 Session API (internal)

```python
SessionManager.create_session(client_type: str) -> Session
SessionManager.get_session(session_id: str) -> Session | None
SessionManager.set_voice_source(session_id: str, client_type: str) -> None
SessionManager.release_voice_source(session_id: str) -> None
SessionManager.end_session(session_id: str) -> None
```

### 10.3 Audio Processing API (internal)

```python
AudioPipeline.process_chunk(chunk: bytes, session: Session) -> None
# Routes to VAD, wake word (if hardware), STT buffer

AudioPipeline.flush(session: Session) -> Transcript
# End of utterance — sends accumulated audio to STT, returns transcript

AudioPipeline.interrupt(session: Session) -> None
# Cancels TTS, drops audio queue
```

### 10.4 Agent API (internal)

```python
AgentRunner.run(transcript: str, session: Session) -> AsyncIterator[AgentEvent]
# Runs the AI agent, yields events (thinking, tool_call, response_chunk, done)

AgentRunner.cancel(session: Session) -> None
# Graceful cancellation on interrupt
```

### 10.5 TTS API (internal)

```python
TTSEngine.synthesize_stream(text: str, session: Session) -> AsyncIterator[bytes]
# Streams PCM chunks as text is generated (low first-chunk latency)

TTSEngine.cancel(session: Session) -> None
```

### 10.6 REST Endpoints (optional utility)

```
GET  /health               → server status + active sessions count
GET  /session/{id}/status  → session state
POST /session/{id}/mode    → force mode switch via REST (for admin/testing)
GET  /session/{id}/transcript → full transcript of current session
```

---

## 11. AI Agent — What It Can Control at Runtime

The AI agent runs server-side and has the following tools it can call. These are the "actions" the AI can take in response to user commands.

### 11.1 Client Control Tools (agent → server → client via WS)

These let the AI reach back and control the client UI/behavior:

| Tool | What it does | Example trigger |
|---|---|---|
| `switch_mode(mode)` | Switches client to conversation/meeting mode | "switch to meeting mode" |
| `set_vad_sensitivity(level)` | Adjusts VAD threshold on client | "be more sensitive" |
| `mute_microphone()` | Tells client to mute itself | "stop listening" |
| `unmute_microphone()` | Tells client to resume | "start listening again" |
| `show_in_chat(content)` | Pushes text/card/link to chatbot UI | "show me the result" |
| `request_image_from_user()` | Prompts user to upload image | "send me a photo of it" |
| `set_wake_word_sensitivity(level)` | Adjusts confidence threshold | after repeated false triggers |

### 11.2 Session Tools (agent → session state)

| Tool | What it does |
|---|---|
| `get_session_transcript()` | Reads full session transcript so far |
| `get_meeting_summary()` | Summarizes meeting transcript with speakers |
| `save_session_note(note)` | Adds a note to session context |
| `get_active_client_type()` | Returns "web" or "hardware" |
| `get_chatbot_attachments()` | Gets any images/links user sent via chatbot |

### 11.3 External/Domain Tools (agent → world)

These are where you plug in your actual capabilities:

| Tool | What it does |
|---|---|
| `web_search(query)` | Search the web |
| `get_weather(location)` | Current weather |
| `read_url(url, instruction?)` | Fetch, clean, and instruction-shape a webpage/link user sent |
| `analyze_image(image_data)` | Describe or answer questions about an image |
| `transcribe_audio(audio_data)` | Transcribe a voice clip user sent via chatbot |
| `set_timer(seconds, label)` | Set a timer, notify client when done |
| `get_time()` | Current time and date |

> **Note:** These are the foundational tools for Phase 1. Domain tools like calendar, smart home, etc. are added in later phases by registering them with the AgentRunner.

---

## 12. React Client — UI Structure

```
┌─────────────────────────────────────────────────────┐
│  VAYUMI                                    [●] Live  │
├─────────────────────────────────────────────────────┤
│                                                     │
│          ┌──────────────────────────┐               │
│          │   Connection Toggle      │               │
│          │   [  Connect  ]          │               │
│          └──────────────────────────┘               │
│                                                     │
│          ┌──────────────────────────┐               │
│          │   Orb / Visualizer       │               │
│          │   (idle/wake/speaking)   │               │
│          └──────────────────────────┘               │
│                                                     │
│  Status: "Listening for Vayumi..."                  │
│  Transcription: "What is the weather in..."         │
│                                                     │
│  [Conversation]    [Meeting Mode]                   │
│                                                     │
├─────────────────────────────────────────────────────┤
│  CHATBOT                                            │
│  ┌─────────────────────────────────────────────────┐│
│  │ AI: The weather today in Chennai is 34°C...     ││
│  │ You: [image attached] What's in this?           ││
│  │ AI: The image shows a circuit board with...     ││
│  └─────────────────────────────────────────────────┘│
│  [ 📎 ] [ 🎤 ] [______ Type a message ______] [Send]│
└─────────────────────────────────────────────────────┘
```

### Key UI States

| State | Orb appearance | Status text |
|---|---|---|
| Disconnected | Grey, static | "Not connected" |
| Connected, idle | Soft pulse | "Listening for Vayumi…" |
| Wake detected | Bright expand | "I'm listening…" |
| Streaming audio | Waveform rings | "Hearing you…" |
| Agent thinking | Slow rotation | "Thinking…" |
| AI speaking | Flowing waves | "Speaking…" |
| Interrupted | Quick flash | "Interrupted" |
| Meeting mode | Blue tint, always active | "Meeting recording…" |

---

## 13. Performance Targets

| Metric | Target |
|---|---|
| Wake word → audio stream start | < 100ms |
| Last speech sample → STT result | < 600ms (streaming STT) |
| STT final → first TTS audio chunk | < 300ms |
| Interrupt signal → audio muted (client) | < 20ms (local mute is instant) |
| Interrupt signal → server flush complete | < 200ms |
| WebSocket reconnect (auto) | < 2s |
| Audio chunk size | 640 bytes (20ms) |
| Max end-to-end latency (wake → first word heard) | < 1.2s |

---

## 14. File Structure (Phase 1)

```
vayumi/
├── client/                        # React app
│   ├── src/
│   │   ├── lib/
│   │   │   ├── VayumiClient.ts    # Main SDK (all WS logic)
│   │   │   ├── AudioWorklet.ts    # Audio capture + resampling
│   │   │   ├── WakeWordEngine.ts  # Wake word wrapper (Porcupine/custom)
│   │   │   ├── VADEngine.ts       # Silero/WebRTC VAD wrapper
│   │   │   └── AudioPlayer.ts     # TTS playback + mute on interrupt
│   │   ├── components/
│   │   │   ├── ConnectToggle.tsx  # The main on/off button
│   │   │   ├── Orb.tsx            # Animated visualizer orb
│   │   │   ├── Transcript.tsx     # Live partial + final text
│   │   │   ├── ChatPanel.tsx      # Chatbot UI
│   │   │   ├── ModeToggle.tsx     # Conversation / Meeting switch
│   │   │   └── StatusBar.tsx      # Connection status
│   │   └── App.tsx
│   └── package.json
│
├── server/                        # Python backend
│   ├── main.py                    # FastAPI app, WS endpoints
│   ├── session/
│   │   ├── manager.py             # SessionManager
│   │   └── models.py              # Session, ClientType, Mode dataclasses
│   ├── audio/
│   │   ├── pipeline.py            # AudioPipeline
│   │   ├── vad.py                 # VAD wrapper (webrtcvad + Silero)
│   │   └── wake_word.py           # OpenWakeWord (for hardware clients)
│   ├── agent/
│   │   ├── runner.py              # AgentRunner (LangChain / custom)
│   │   ├── tools/
│   │   │   ├── client_control.py  # Tools that send WS events to client
│   │   │   ├── session_tools.py   # Tools that read/write session
│   │   │   └── external.py        # Web search, weather, image analysis
│   │   └── prompts.py
│   ├── tts/
│   │   └── engine.py              # TTS streaming wrapper
│   ├── stt/
│   │   └── engine.py              # STT streaming wrapper (Whisper/Deepgram)
│   └── diarization/
│       └── engine.py              # Speaker diarization (meeting mode)
│
└── docs/
    └── vayumi-platform-spec.md    # ← this document
```

---

## 15. What to Build Next (Phase 2+)

This document covers Phase 1: the WebSocket layer and React client. After this is stable:

| Phase | What |
|---|---|
| 2 | STT integration (Whisper streaming or Deepgram) |
| 3 | AI agent core + tool registry |
| 4 | TTS integration + audio playback pipeline |
| 5 | ESP32-S3 firmware (WebSocket client, I2S mic, DAC speaker) |
| 6 | Meeting mode — diarization pipeline |
| 7 | Chatbot image/link/voice analysis |
| 8 | Wake word custom training ("Vayumi" model) |
| 9 | Mobile PWA packaging |

---

*Document version: 1.0 — Phase 1 scope*
*Project: Vayumi AI Agent Platform*