// =============================================================================
// client/browser/app.js — Login, WebSocket, Audio Capture/Playback
// =============================================================================
//
// PURPOSE:
//   Core client logic for the Vayumi browser client. Handles:
//   - User login (POST /api/auth/login → JWT token)
//   - WebSocket connection to server
//   - Authentication over WebSocket (first message: {type:"auth", token:...})
//   - Microphone audio capture and streaming
//   - Audio playback of TTS responses
//   - Message routing (incoming server messages → UI updates)
//
// STATE:
//   let authToken = null;        // JWT token from login
//   let userId = null;           // Authenticated user ID
//   let sessionId = null;        // Server-assigned session ID
//   let ws = null;               // WebSocket connection
//   let mediaStream = null;      // Microphone MediaStream
//   let audioContext = null;     // AudioContext for playback
//   let isActivated = false;     // Whether mic is active (ACTIVE state)
//   let currentMode = "normal";  // Current mode
//
// FUNCTIONS:
//
//   async login(email, password):
//     POST /api/auth/login with {email, password}
//     On success: store authToken, call connectWebSocket()
//     On failure: show error via ui.showLoginError()
//
//   connectWebSocket():
//     Opens WebSocket to ws://<host>/ws/vayumi
//     ws.onopen → send {type:"auth", token:authToken}
//     ws.onmessage → routeMessage(data)
//     ws.onclose → ui.showDisconnected(), attempt reconnect after 3s
//     ws.onerror → log error
//
//   routeMessage(data):
//     Parses incoming JSON message and routes to handler:
//       "auth_ok"        → store userId, sessionId, ui.showMainInterface()
//       "auth_error"     → ui.showLoginError(data.message)
//       "status"         → ui.updateStatus(data.state)
//       "sleep"          → deactivateMic(), ui.updateStatus("sleeping")
//       "transcript"     → ui.addTranscript(data.text, data.speaker)
//       "response_text"  → ui.addResponse(data.text, data.is_final)
//       "audio_chunk"    → playAudioChunk(data.data)
//       "mode_changed"   → currentMode = data.mode, ui.updateMode(data.mode)
//       "flag_notify"    → ui.showNotification(data.source, data.preview)
//       "error"          → ui.showError(data.message)
//
//   async activateMic():
//     Called when user clicks mic button.
//     1. ws.send({type:"wake"})
//     2. Request mic permission: navigator.mediaDevices.getUserMedia({
//          audio: {echoCancellation:true, sampleRate:16000, channelCount:1}
//        })
//     3. Set up MediaRecorder or AudioWorklet to capture audio chunks
//     4. On audio data: base64 encode → ws.send({type:"audio_chunk", data:...})
//     5. isActivated = true
//
//   deactivateMic():
//     Stops MediaRecorder/AudioWorklet. Closes mediaStream tracks.
//     isActivated = false
//
//   playAudioChunk(base64Data):
//     1. Decode base64 to ArrayBuffer
//     2. Decode WAV via audioContext.decodeAudioData
//     3. Create BufferSourceNode, connect to destination, play
//     4. Queue chunks for sequential playback
//     5. When last chunk finishes → ws.send({type:"playback_done"})
//
//   sendTextInput(text):
//     ws.send({type:"text_input", text:text})
//
//   sendInterrupt(action = "stop"):
//     ws.send({type:"interrupt", action:action})
//
//   sendModeSwitch(mode):
//     ws.send({type:"mode_switch", mode:mode})
//
//   sendSpeakerLabel(speakerId, name):
//     ws.send({type:"speaker_label", speaker_id:speakerId, name:name})
//
// EVENT LISTENERS:
//   - Login form submit → login()
//   - Mic button click → activateMic() or deactivateMic()
//   - Text input enter → sendTextInput()
//   - Mode button click → sendModeSwitch()
//   - Interrupt button → sendInterrupt()
// =============================================================================

let authToken = null;
let userId = null;
let sessionId = null;
let ws = null;
let mediaStream = null;
let audioContext = null;
let isActivated = false;
let currentMode = "normal";

function login(email, password) {}
function connectWebSocket() {}
function routeMessage(data) {}
function activateMic() {}
function deactivateMic() {}
function playAudioChunk(base64Data) {}
function sendTextInput(text) {}
function sendInterrupt(action) {}
function sendModeSwitch(mode) {}
function sendSpeakerLabel(speakerId, name) {}
