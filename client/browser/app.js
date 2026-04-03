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

// let authToken = null;
// let userId = null;
// let sessionId = null;
// let ws = null;
// let mediaStream = null;
// let audioContext = null;
// let isActivated = false;
// let currentMode = "normal";

// function login(email, password) {}
// function connectWebSocket() {}
// function routeMessage(data) {}
// function activateMic() {}
// function deactivateMic() {}
// function playAudioChunk(base64Data) {}
// function sendTextInput(text) {}
// function sendInterrupt(action) {}
// function sendModeSwitch(mode) {}
// function sendSpeakerLabel(speakerId, name) {}


// =============================================================================
// client/browser/app.js — Login, WebSocket, Audio Capture/Playback
// =============================================================================

let authToken = null;
let userId = null;
let sessionId = null;
let ws = null;
let mediaStream = null;
let audioContext = null;
let isActivated = false;
let currentMode = "normal";

// Audio playback queue for sequential chunk playback
let audioQueue = [];
let isPlaying = false;
let mediaRecorder = null;
let reconnectTimer = null;

// ---------------------------------------------------------------------------
// HTTP helpers (FastAPI uses { "detail": "..." } for errors)
// ---------------------------------------------------------------------------

function _httpDetail(payload) {
  const d = payload?.detail;
  if (typeof d === "string") return d;
  if (Array.isArray(d)) return d.map((x) => x.msg || JSON.stringify(x)).join("; ");
  return payload?.message ?? null;
}

// ---------------------------------------------------------------------------
// Login / Register
// ---------------------------------------------------------------------------

async function login(email, password) {
  try {
    const response = await fetch("/api/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password }),
    });

    if (!response.ok) {
      const errBody = await response.json().catch(() => ({}));
      ui.showLoginError(_httpDetail(errBody) || `Login failed (${response.status})`);
      return;
    }

    const result = await response.json();
    authToken = result.token;
    connectWebSocket();
  } catch (err) {
    console.error("[app] login error:", err);
    ui.showLoginError("Network error — could not reach server.");
  }
}

async function registerAccount(displayName, email, password) {
  try {
    const response = await fetch("/api/auth/register", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        display_name: displayName,
        email,
        password,
      }),
    });

    const body = await response.json().catch(() => ({}));
    if (!response.ok) {
      ui.showLoginError(_httpDetail(body) || `Registration failed (${response.status})`);
      return;
    }

    ui.clearAuthError();
    ui.showAuthSuccessHint("Account created. You can sign in below.");
    ui.showLoginPanel();
    const emailInput = document.getElementById("email");
    const passInput = document.getElementById("password");
    if (emailInput) emailInput.value = email;
    if (passInput) {
      passInput.value = "";
      passInput.focus();
    }
  } catch (err) {
    console.error("[app] register error:", err);
    ui.showLoginError("Network error — could not reach server.");
  }
}

// ---------------------------------------------------------------------------
// WebSocket
// ---------------------------------------------------------------------------

function connectWebSocket() {
  if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) {
    ws.close();
  }

  const protocol = location.protocol === "https:" ? "wss:" : "ws:";
  const url = `${protocol}//${location.host}/ws/vayumi`;

  ws = new WebSocket(url);

  ws.onopen = () => {
    console.log("[app] WebSocket connected — sending auth");
    if (reconnectTimer) {
      clearTimeout(reconnectTimer);
      reconnectTimer = null;
    }
    ws.send(JSON.stringify({ type: "auth", token: authToken }));
  };

  ws.onmessage = (event) => {
    try {
      const data = typeof event.data === "string" ? JSON.parse(event.data) : event.data;
      routeMessage(data);
    } catch (err) {
      console.error("[app] Failed to parse message:", err, event.data);
    }
  };

  ws.onclose = (event) => {
    console.warn("[app] WebSocket closed:", event.code, event.reason);
    ui.showDisconnected();
    // Attempt reconnect after 3 seconds
    if (!reconnectTimer) {
      reconnectTimer = setTimeout(() => {
        reconnectTimer = null;
        if (authToken) {
          console.log("[app] Attempting reconnect…");
          connectWebSocket();
        }
      }, 3000);
    }
  };

  ws.onerror = (err) => {
    console.error("[app] WebSocket error:", err);
  };
}

// ---------------------------------------------------------------------------
// Message Router
// ---------------------------------------------------------------------------

function routeMessage(data) {
  console.debug("[app] ws message:", data);
  switch (data.type) {
    case "auth_ok":
      userId = data.user_id;
      sessionId = data.session_id;
      console.log("[app] Authenticated — user:", userId, "session:", sessionId);
      ui.showMainInterface();
      ui.hideDisconnected();
      ui.clearTranscript();
      ui.updateStatus("sleeping");
      break;

    case "auth_error":
      ui.showLoginError(data.message || "Authentication failed.");
      break;

    case "status":
      ui.updateStatus(data.state);
      break;

    case "sleep":
      deactivateMic();
      ui.updateStatus("sleeping");
      break;

    case "transcript":
      ui.addTranscript(data.text, data.speaker);
      break;

    case "response_text":
      ui.addResponse(data.text, data.is_final);
      break;

    case "audio_chunk":
      playAudioChunk(data.data);
      break;

    case "mode_changed":
      currentMode = data.mode;
      ui.updateMode(data.mode);
      break;

    case "flag_notify":
      ui.showNotification(data.source, data.preview);
      break;

    case "error":
      ui.showError(data.message);
      break;

    default:
      console.warn("[app] Unknown message type:", data.type, data);
  }
}

// ---------------------------------------------------------------------------
// Microphone Capture
// ---------------------------------------------------------------------------

async function activateMic() {
  if (isActivated) return;

  // Notify server we're waking up
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ type: "wake" }));
  }

  try {
    mediaStream = await navigator.mediaDevices.getUserMedia({
      audio: {
        echoCancellation: true,
        sampleRate: 16000,
        channelCount: 1,
      },
    });
  } catch (err) {
    console.error("[app] Microphone access denied:", err);
    ui.showError("Microphone access denied. Please allow mic permissions.");
    return;
  }

  // Prefer AudioWorklet for low-latency streaming; fall back to MediaRecorder
  if (audioContext && audioContext.state === "closed") {
    audioContext = null;
  }
  if (!audioContext) {
    audioContext = new (window.AudioContext || window.webkitAudioContext)({
      sampleRate: 16000,
    });
  }
  if (audioContext.state === "suspended") {
    await audioContext.resume();
  }

  try {
    await _startAudioWorklet();
  } catch (_workletErr) {
    console.warn("[app] AudioWorklet unavailable, falling back to MediaRecorder");
    _startMediaRecorder();
  }

  isActivated = true;
}

// --- AudioWorklet path -------------------------------------------------------

async function _startAudioWorklet() {
  // Register a minimal processor inline via a Blob so we don't need a separate file.
  const processorCode = `
    class CaptureProcessor extends AudioWorkletProcessor {
      process(inputs) {
        const input = inputs[0];
        if (input && input[0] && input[0].length > 0) {
          this.port.postMessage(input[0]); // Float32Array
        }
        return true;
      }
    }
    registerProcessor("capture-processor", CaptureProcessor);
  `;
  const blob = new Blob([processorCode], { type: "application/javascript" });
  const blobUrl = URL.createObjectURL(blob);

  await audioContext.audioWorklet.addModule(blobUrl);
  URL.revokeObjectURL(blobUrl);

  const source = audioContext.createMediaStreamSource(mediaStream);
  const workletNode = new AudioWorkletNode(audioContext, "capture-processor");

  workletNode.port.onmessage = (event) => {
    const float32 = event.data; // Float32Array
    const pcm16 = _float32ToPcm16(float32);
    const base64 = _arrayBufferToBase64(pcm16.buffer);
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: "audio_chunk", data: base64 }));
    }
  };

  source.connect(workletNode);
  workletNode.connect(audioContext.destination); // needed to keep graph alive (silent)

  // Stash references so we can tear down later
  mediaStream._workletSource = source;
  mediaStream._workletNode = workletNode;
}

// --- MediaRecorder fallback --------------------------------------------------

function _startMediaRecorder() {
  const mimeType = MediaRecorder.isTypeSupported("audio/webm;codecs=opus")
    ? "audio/webm;codecs=opus"
    : "audio/webm";

  mediaRecorder = new MediaRecorder(mediaStream, {
    mimeType,
    audioBitsPerSecond: 16000,
  });

  mediaRecorder.ondataavailable = async (event) => {
    if (event.data && event.data.size > 0) {
      const buffer = await event.data.arrayBuffer();
      const base64 = _arrayBufferToBase64(buffer);
      if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: "audio_chunk", data: base64 }));
      }
    }
  };

  // Capture in small slices (250 ms)
  mediaRecorder.start(250);
}

function deactivateMic() {
  if (mediaRecorder) {
    try {
      mediaRecorder.stop();
    } catch (_) {
      /* ignore if already stopped */
    }
    mediaRecorder = null;
  }

  if (mediaStream) {
    // Tear down worklet nodes if present
    if (mediaStream._workletSource) {
      try {
        mediaStream._workletSource.disconnect();
      } catch (_) {}
    }
    if (mediaStream._workletNode) {
      try {
        mediaStream._workletNode.disconnect();
        mediaStream._workletNode.port.close();
      } catch (_) {}
    }
    // Stop all tracks
    mediaStream.getTracks().forEach((track) => track.stop());
    mediaStream = null;
  }

  isActivated = false;
}

// ---------------------------------------------------------------------------
// Audio Playback (queued sequential chunks)
// ---------------------------------------------------------------------------

function playAudioChunk(base64Data) {
  if (!audioContext || audioContext.state === "closed") {
    audioContext = new (window.AudioContext || window.webkitAudioContext)();
  }
  if (audioContext.state === "suspended") {
    audioContext.resume();
  }

  const raw = _base64ToArrayBuffer(base64Data);
  audioQueue.push(raw);

  if (!isPlaying) {
    _playNextChunk();
  }
}

function _playNextChunk() {
  if (audioQueue.length === 0) {
    isPlaying = false;
    // Notify server that all queued audio has finished playing
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: "playback_done" }));
    }
    return;
  }

  isPlaying = true;
  const buffer = audioQueue.shift();

  audioContext.decodeAudioData(
    buffer,
    (audioBuffer) => {
      const source = audioContext.createBufferSource();
      source.buffer = audioBuffer;
      source.connect(audioContext.destination);
      source.onended = () => {
        _playNextChunk();
      };
      source.start(0);
    },
    (err) => {
      console.error("[app] decodeAudioData error:", err);
      // Skip bad chunk, continue with next
      _playNextChunk();
    }
  );
}

// ---------------------------------------------------------------------------
// Outgoing Message Helpers
// ---------------------------------------------------------------------------

function sendTextInput(text) {
  if (!text) return;
  if (ws && ws.readyState === WebSocket.OPEN) {
    console.info("[app] sending text input:", text);
    ws.send(JSON.stringify({ type: "text_input", text }));
  } else {
    ui.showError("Not connected yet. Please wait for the session to finish connecting.");
  }
}

function sendInterrupt(action = "stop") {
  // Also flush the local audio queue immediately
  audioQueue.length = 0;
  isPlaying = false;

  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ type: "interrupt", action }));
  }
}

function sendModeSwitch(mode) {
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ type: "mode_switch", mode }));
  }
}

function sendSpeakerLabel(speakerId, name) {
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ type: "speaker_label", speaker_id: speakerId, name }));
  }
}

// ---------------------------------------------------------------------------
// Binary / Encoding Helpers
// ---------------------------------------------------------------------------

function _float32ToPcm16(float32Array) {
  const pcm16 = new Int16Array(float32Array.length);
  for (let i = 0; i < float32Array.length; i++) {
    let s = float32Array[i];
    s = s < -1 ? -1 : s > 1 ? 1 : s;
    pcm16[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
  }
  return pcm16;
}

function _arrayBufferToBase64(buffer) {
  const bytes = new Uint8Array(buffer);
  let binary = "";
  for (let i = 0; i < bytes.byteLength; i++) {
    binary += String.fromCharCode(bytes[i]);
  }
  return btoa(binary);
}

function _base64ToArrayBuffer(base64) {
  const binary = atob(base64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) {
    bytes[i] = binary.charCodeAt(i);
  }
  return bytes.buffer;
}

// ---------------------------------------------------------------------------
// DOM Event Listeners (wired up once DOM is ready)
// ---------------------------------------------------------------------------

document.addEventListener("DOMContentLoaded", () => {
  document.getElementById("link-show-register")?.addEventListener("click", (e) => {
    e.preventDefault();
    ui.clearAuthError();
    ui.hideAuthSuccessHint();
    ui.showRegisterPanel();
  });
  document.getElementById("link-show-login")?.addEventListener("click", (e) => {
    e.preventDefault();
    ui.clearAuthError();
    ui.hideAuthSuccessHint();
    ui.showLoginPanel();
  });

  // Login form
  const loginForm = document.getElementById("login-form");
  if (loginForm) {
    loginForm.addEventListener("submit", (e) => {
      e.preventDefault();
      ui.hideAuthSuccessHint();
      const email = document.getElementById("email")?.value?.trim();
      const password = document.getElementById("password")?.value;
      if (email && password) {
        login(email, password);
      }
    });
  }

  const registerForm = document.getElementById("register-form");
  if (registerForm) {
    registerForm.addEventListener("submit", (e) => {
      e.preventDefault();
      ui.hideAuthSuccessHint();
      const displayName = document.getElementById("reg-display-name")?.value?.trim();
      const email = document.getElementById("reg-email")?.value?.trim();
      const password = document.getElementById("reg-password")?.value;
      if (displayName && email && password) {
        registerAccount(displayName, email, password);
      }
    });
  }

  // Mic toggle button
  const micBtn = document.getElementById("mic-btn");
  if (micBtn) {
    micBtn.addEventListener("click", () => {
      if (isActivated) {
        deactivateMic();
        micBtn.classList.remove("active");
      } else {
        activateMic().then(() => {
          if (isActivated) micBtn.classList.add("active");
        });
      }
    });
  }

  // Text input — shared submit logic
  const textInput = document.getElementById("text-input");

  function _submitTextInput() {
    if (!textInput) return;
    const text = textInput.value.trim();
    if (!text) return;
    ui.addTranscript(text, "user");
    sendTextInput(text);
    textInput.value = "";
  }

  if (textInput) {
    textInput.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        _submitTextInput();
      }
    });
  }

  const textSendBtn = document.getElementById("text-send-btn");
  if (textSendBtn) {
    textSendBtn.addEventListener("click", () => {
      _submitTextInput();
      if (textInput) textInput.focus();
    });
  }

  // Mode buttons (data-mode attribute)
  document.querySelectorAll("[data-mode]").forEach((btn) => {
    btn.addEventListener("click", () => {
      sendModeSwitch(btn.dataset.mode);
    });
  });

  // Interrupt button
  const interruptBtn = document.getElementById("interrupt-btn");
  if (interruptBtn) {
    interruptBtn.addEventListener("click", () => {
      sendInterrupt("stop");
    });
  }
});