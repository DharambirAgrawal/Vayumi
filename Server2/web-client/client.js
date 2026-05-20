(function () {
  "use strict";

  const $ = (id) => document.getElementById(id);

  const connStatus = $("connStatus");
  const modeBadge = $("modeBadge");
  const tokenEl = $("token");
  const btnConnect = $("btnConnect");
  const btnDisconnect = $("btnDisconnect");
  const modeSelect = $("modeSelect");
  const btnMic = $("btnMic");
  const btnInterrupt = $("btnInterrupt");
  const captionText = $("captionText");
  const chatThread = $("chatThread");
  const chatInput = $("chatInput");
  const btnSend = $("btnSend");
  const activityFeed = $("activityFeed");
  const playbackStateEl = $("playbackState");
  const captureStateEl = $("captureState");
  const btnDebug = $("btnDebug");
  const debugLog = $("debugLog");

  let ws = null;
  let sessionMode = "conversation";
  let captionBuffer = "";
  let activityEvents = [];

  let playbackCtx = null;
  let playbackGain = null;
  let nextPlayTime = 0;
  let activeSources = [];
  let pendingAudioRate = 16000;
  let ducking = false;

  let micStream = null;
  let micAudioCtx = null;
  let micWorkletNode = null;
  let micRecording = false;

  const clientState = {
    playback: "idle",
    capture: "idle",
    visible: true,
    route: "speaker",
  };

  function setConnStatus(state) {
    connStatus.textContent = state;
    connStatus.className = "badge " + state;
    const connected = state === "connected";
    btnConnect.disabled = connected;
    btnDisconnect.disabled = !connected;
    modeSelect.disabled = !connected;
    btnMic.disabled = !connected;
    btnInterrupt.disabled = !connected;
    chatInput.disabled = !connected;
    btnSend.disabled = !connected;
  }

  function updateAudioStatusUi() {
    playbackStateEl.textContent = clientState.playback;
    captureStateEl.textContent = clientState.capture;
  }

  function debugLine(text, cls) {
    const row = document.createElement("div");
    row.className = "line " + (cls || "");
    row.textContent = text;
    debugLog.appendChild(row);
    debugLog.scrollTop = debugLog.scrollHeight;
    while (debugLog.childNodes.length > 80) {
      debugLog.removeChild(debugLog.firstChild);
    }
  }

  function sendJson(type, payload) {
    if (!ws || ws.readyState !== WebSocket.OPEN) return;
    const msg = JSON.stringify({ type: type, payload: payload });
    ws.send(msg);
    debugLine(">>> " + msg, "sent");
  }

  function sendPcmFrame(arrayBuffer) {
    if (!ws || ws.readyState !== WebSocket.OPEN) return;
    ws.send(arrayBuffer);
  }

  function reportClientState() {
    sendJson("client_state", {
      playback: clientState.playback,
      capture: clientState.capture,
      visible: document.visibilityState === "visible",
      route: clientState.route,
    });
    updateAudioStatusUi();
  }

  function setPlayback(state) {
    clientState.playback = state;
    reportClientState();
  }

  function setCapture(state) {
    clientState.capture = state;
    reportClientState();
  }

  function connect(token) {
    if (!token) {
      debugLine("Error: enter a token", "error");
      return;
    }

    const proto = location.protocol === "https:" ? "wss:" : "ws:";
    const url =
      proto + "//" + location.host + "/ws/v1/session?token=" + encodeURIComponent(token);

    setConnStatus("connecting");
    debugLine("Connecting to " + url);

    ws = new WebSocket(url);
    ws.binaryType = "arraybuffer";

    ws.onopen = function () {
      setConnStatus("connected");
      debugLine("WebSocket open");
      sendJson("hello", {
        client: "web",
        capabilities: { aec: true, vad: false, wake: false },
      });
      reportClientState();
    };

    ws.onmessage = function (ev) {
      if (typeof ev.data === "string") {
        debugLine("<<< " + ev.data, "recv");
        handleServerJson(ev.data);
      } else if (ev.data instanceof ArrayBuffer) {
        handleServerAudio(ev.data, pendingAudioRate);
      }
    };

    ws.onclose = function (ev) {
      setConnStatus("closed");
      stopMic();
      stopPlayback();
      debugLine("Closed: code=" + ev.code + " " + (ev.reason || ""));
      ws = null;
    };

    ws.onerror = function () {
      debugLine("WebSocket error", "error");
    };
  }

  function disconnect() {
    if (ws) ws.close();
  }

  function sendChat(text, attachments) {
    const payload = { text: text };
    if (attachments && attachments.length) payload.attachments = attachments;
    sendJson("chat", payload);
    appendChatBubble("user", text);
  }

  function sendMode(mode) {
    sessionMode = mode;
    sendJson("mode", { mode: mode });
    modeBadge.textContent = mode;
    modeBadge.className = "badge" + (mode === "meeting" ? " mode-meeting" : "");
  }

  function handleServerJson(raw) {
    let msg;
    try {
      msg = JSON.parse(raw);
    } catch (_) {
      return;
    }

    switch (msg.type) {
      case "caption":
        renderCaption(msg.payload.text, msg.payload.partial);
        break;
      case "audio_start":
        pendingAudioRate = msg.payload.sample_rate || 16000;
        handleClientControl({ command: "clear_queue", reason: "audio_start" });
        setPlayback("playing");
        break;
      case "audio_end":
        schedulePlaybackIdle();
        break;
      case "client_control":
        handleClientControl(msg.payload);
        break;
      case "event":
        renderEvent(msg.payload);
        break;
      case "error":
        debugLine("Server error: " + msg.payload.message, "error");
        break;
      default:
        break;
    }
  }

  function schedulePlaybackIdle() {
    const check = function () {
      if (activeSources.length === 0) {
        setPlayback("idle");
      } else {
        setTimeout(check, 100);
      }
    };
    setTimeout(check, 50);
  }

  function renderCaption(text, partial) {
    if (partial) {
      captionBuffer += text;
    } else {
      captionBuffer = text;
      if (text.trim()) {
        appendChatBubble("assistant", text);
      }
      captionBuffer = "";
    }
    if (captionBuffer.trim()) {
      captionText.textContent = captionBuffer;
      captionText.classList.remove("empty");
    } else if (!partial && text.trim()) {
      captionText.textContent = text;
      captionText.classList.remove("empty");
    } else if (!partial) {
      captionText.textContent = "Waiting for assistant…";
      captionText.classList.add("empty");
    }
  }

  function appendChatBubble(role, text) {
    const bubble = document.createElement("div");
    bubble.className = "bubble " + role;
    const meta = document.createElement("div");
    meta.className = "meta";
    meta.textContent = role === "user" ? "You" : "Vayumi";
    const body = document.createElement("p");
    body.textContent = text;
    bubble.appendChild(meta);
    bubble.appendChild(body);
    chatThread.appendChild(bubble);
    chatThread.scrollTop = chatThread.scrollHeight;
  }

  function renderEvent(event) {
    activityEvents.push(event);
    renderTaskBoard(activityEvents);
  }

  function renderTaskBoard(events) {
    activityFeed.innerHTML = "";
    if (!events.length) {
      const empty = document.createElement("p");
      empty.className = "empty";
      empty.textContent = "No background tasks yet.";
      activityFeed.appendChild(empty);
      return;
    }
    events.slice(-30).forEach(function (ev) {
      const pill = document.createElement("div");
      pill.className = "event-pill";
      pill.innerHTML =
        '<span class="kind">' +
        ev.kind +
        "</span> · " +
        (ev.summary || "").replace(/</g, "&lt;");
      activityFeed.appendChild(pill);
    });
    activityFeed.scrollTop = activityFeed.scrollHeight;
  }

  function ensurePlaybackContext(sampleRate) {
    if (!playbackCtx || playbackCtx.sampleRate !== sampleRate) {
      playbackCtx = new AudioContext({ sampleRate: sampleRate });
      playbackGain = playbackCtx.createGain();
      playbackGain.connect(playbackCtx.destination);
      nextPlayTime = playbackCtx.currentTime;
    }
    return playbackCtx;
  }

  function applyDuck() {
    if (!playbackGain) return;
    playbackGain.gain.value = ducking ? 0.2 : 1.0;
  }

  function stopPlayback() {
    activeSources.forEach(function (source) {
      try {
        source.stop();
      } catch (_) {}
    });
    activeSources = [];
    if (playbackCtx) {
      nextPlayTime = playbackCtx.currentTime;
    }
    setPlayback("idle");
  }

  function handleServerAudio(arrayBuffer, sampleRate) {
    const ctx = ensurePlaybackContext(sampleRate);
    const int16 = new Int16Array(arrayBuffer);
    const float32 = new Float32Array(int16.length);
    for (let i = 0; i < int16.length; i++) {
      float32[i] = int16[i] / 32768;
    }

    const buffer = ctx.createBuffer(1, float32.length, sampleRate);
    buffer.copyToChannel(float32, 0);
    const source = ctx.createBufferSource();
    source.buffer = buffer;
    source.connect(playbackGain);

    const startAt = Math.max(ctx.currentTime, nextPlayTime);
    source.start(startAt);
    nextPlayTime = startAt + buffer.duration;
    activeSources.push(source);
    clientState.playback = "playing";
    updateAudioStatusUi();

    source.onended = function () {
      activeSources = activeSources.filter(function (s) {
        return s !== source;
      });
      if (activeSources.length === 0) {
        setPlayback("idle");
      }
    };
  }

  function handleClientControl(payload) {
    const cmd = payload.command;
    const reason = payload.reason || "";

    switch (cmd) {
      case "play":
        if (playbackCtx && playbackCtx.state === "suspended") {
          playbackCtx.resume();
        }
        setPlayback(activeSources.length ? "playing" : clientState.playback);
        break;
      case "pause":
        setPlayback("paused");
        break;
      case "stop":
      case "clear_queue":
        stopPlayback();
        break;
      case "duck":
        ducking = true;
        applyDuck();
        break;
      case "unduck":
        ducking = false;
        applyDuck();
        break;
      case "start_capture":
        if (!micRecording) startMic();
        break;
      case "stop_capture":
        if (micRecording) stopMic();
        break;
      default:
        debugLine("Unknown client_control: " + cmd, "error");
    }

    debugLine("client_control " + cmd + " (" + reason + ")", "info");
    reportClientState();
  }

  async function startMic() {
    if (micRecording || !ws) return;

    try {
      micStream = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          channelCount: 1,
          sampleRate: 16000,
        },
      });
    } catch (err) {
      debugLine("Mic error: " + err.message, "error");
      return;
    }

    micAudioCtx = new AudioContext({ sampleRate: 16000 });
    const source = micAudioCtx.createMediaStreamSource(micStream);

    const workletCode =
      'class PcmCapture extends AudioWorkletProcessor {\n' +
      "  process(inputs) {\n" +
      "    const ch = inputs[0][0];\n" +
      "    if (ch) {\n" +
      "      const i16 = new Int16Array(ch.length);\n" +
      "      for (let i = 0; i < ch.length; i++) {\n" +
      "        const s = Math.max(-1, Math.min(1, ch[i]));\n" +
      "        i16[i] = s < 0 ? s * 0x8000 : s * 0x7FFF;\n" +
      "      }\n" +
      "      this.port.postMessage(i16.buffer, [i16.buffer]);\n" +
      "    }\n" +
      "    return true;\n" +
      "  }\n" +
      "}\n" +
      'registerProcessor("pcm-capture", PcmCapture);';

    const blob = new Blob([workletCode], { type: "application/javascript" });
    const workletUrl = URL.createObjectURL(blob);

    try {
      await micAudioCtx.audioWorklet.addModule(workletUrl);
    } catch (err) {
      debugLine("AudioWorklet error: " + err.message, "error");
      micStream.getTracks().forEach(function (t) {
        t.stop();
      });
      await micAudioCtx.close();
      micStream = null;
      micAudioCtx = null;
      URL.revokeObjectURL(workletUrl);
      return;
    }

    micWorkletNode = new AudioWorkletNode(micAudioCtx, "pcm-capture");
    source.connect(micWorkletNode);
    micWorkletNode.connect(micAudioCtx.destination);

    micWorkletNode.port.onmessage = function (ev) {
      sendPcmFrame(ev.data);
    };

    sendJson("audio_start", { sample_rate: 16000, format: "pcm_s16le" });
    micRecording = true;
    btnMic.textContent = "Stop mic";
    btnMic.classList.add("mic-active");
    setCapture("recording");
    URL.revokeObjectURL(workletUrl);
  }

  async function stopMic() {
    if (!micRecording) return;

    if (micWorkletNode) {
      micWorkletNode.port.onmessage = null;
      micWorkletNode.disconnect();
      micWorkletNode = null;
    }
    if (micStream) {
      micStream.getTracks().forEach(function (t) {
        t.stop();
      });
      micStream = null;
    }
    if (micAudioCtx) {
      await micAudioCtx.close();
      micAudioCtx = null;
    }

    sendJson("audio_end", {});
    micRecording = false;
    btnMic.textContent = "Mic";
    btnMic.classList.remove("mic-active");
    setCapture("idle");
  }

  function toggleMic() {
    if (micRecording) {
      stopMic();
    } else {
      startMic();
    }
  }

  function sendInterrupt() {
    handleClientControl({ command: "stop", reason: "local_interrupt" });
    handleClientControl({ command: "clear_queue", reason: "local_interrupt" });
    sendJson("interrupt", { source: "button" });
  }

  document.addEventListener("visibilitychange", function () {
    if (ws && ws.readyState === WebSocket.OPEN) {
      reportClientState();
    }
  });

  btnConnect.addEventListener("click", function () {
    connect(tokenEl.value.trim());
  });
  btnDisconnect.addEventListener("click", disconnect);
  btnSend.addEventListener("click", function () {
    const text = chatInput.value.trim();
    if (!text) return;
    sendChat(text);
    chatInput.value = "";
  });
  chatInput.addEventListener("keydown", function (e) {
    if (e.key === "Enter") btnSend.click();
  });
  btnMic.addEventListener("click", toggleMic);
  btnInterrupt.addEventListener("click", sendInterrupt);
  modeSelect.addEventListener("change", function () {
    sendMode(modeSelect.value);
  });
  btnDebug.addEventListener("click", function () {
    const show = !debugLog.classList.contains("visible");
    debugLog.classList.toggle("visible", show);
    btnDebug.textContent = show ? "Hide debug log" : "Show debug log";
  });

  setConnStatus("closed");
  updateAudioStatusUi();
})();
