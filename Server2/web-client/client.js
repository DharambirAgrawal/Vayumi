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
  let conversationStatusEl = null;

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
  let micUserMuted = false;
  let pendingStartCapture = false;
  let meetingChunkTimer = null;
  const MEETING_CHUNK_MS = 30000;

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

  function escapeHtml(text) {
    return String(text || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");
  }

  function compactSummary(summary, fallback) {
    const firstLine = String(summary || "").split(/\n+/)[0].trim();
    const text = firstLine || fallback || "";
    if (text.length <= 140) return text;
    return text.slice(0, 137).trimEnd() + "...";
  }

  function resetTransientUi() {
    captionBuffer = "";
    activityEvents = [];
    clearConversationStatus();
    captionText.textContent = "Waiting for assistant…";
    captionText.classList.add("empty");
    chatThread.innerHTML = "";
    renderTaskBoard(activityEvents);
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

  let clientStateTimer = null;
  let lastReportedState = "";
  let visibilityTimer = null;
  let effectiveVisible = true;

  function isClientVisible() {
    return (
      document.visibilityState === "visible" ||
      (typeof document.hasFocus === "function" && document.hasFocus())
    );
  }

  function reportClientState() {
    const currentlyVisible = isClientVisible();
    if (currentlyVisible) {
      effectiveVisible = true;
      if (visibilityTimer) {
        clearTimeout(visibilityTimer);
        visibilityTimer = null;
      }
      _doReport();
    } else {
      if (!visibilityTimer && effectiveVisible) {
        visibilityTimer = setTimeout(function() {
          effectiveVisible = false;
          visibilityTimer = null;
          _doReport();
        }, 1000);
      }
      _doReport();
    }
  }

  function _doReport() {
    const snapshot = JSON.stringify({
      playback: clientState.playback,
      capture: clientState.capture,
      visible: effectiveVisible,
      route: clientState.route,
    });
    if (snapshot === lastReportedState) {
      updateAudioStatusUi();
      return;
    }
    if (clientStateTimer) {
      clearTimeout(clientStateTimer);
    }
    clientStateTimer = setTimeout(function () {
      clientStateTimer = null;
      lastReportedState = snapshot;
      const parsed = JSON.parse(snapshot);
      sendJson("client_state", parsed);
      updateAudioStatusUi();
    }, 400);
  }

  function setPlayback(state) {
    const was = clientState.playback;
    clientState.playback = state;
    reportClientState();
    if (
      was === "playing" &&
      state === "idle" &&
      pendingStartCapture &&
      !micUserMuted &&
      !micRecording
    ) {
      pendingStartCapture = false;
      startMic();
    }
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
      resetTransientUi();
      setConnStatus("connected");
      debugLine("WebSocket open");
      const helloPayload = {
        client: "web",
        capabilities: { aec: true, vad: false, wake: false, tts: true },
      };
      if (token === "dev") {
        helloPayload.session_id =
          "dev-" + (crypto.randomUUID ? crypto.randomUUID() : String(Date.now()));
      }
      sendJson("hello", helloPayload);
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
    clientState.visible = true;
    reportClientState();
    const payload = { text: text };
    if (attachments && attachments.length) payload.attachments = attachments;
    sendJson("chat", payload);
    appendChatBubble("user", text);
  }

  function stopMeetingChunkTimer() {
    if (meetingChunkTimer) {
      clearInterval(meetingChunkTimer);
      meetingChunkTimer = null;
    }
  }

  function startMeetingChunkTimer() {
    stopMeetingChunkTimer();
    if (sessionMode !== "meeting") return;
    meetingChunkTimer = setInterval(function () {
      if (sessionMode !== "meeting" || micUserMuted || !micRecording) return;
      stopMic({ sendAudioEnd: true, meetingRestart: true });
    }, MEETING_CHUNK_MS);
  }

  function applyMeetingModeUi(mode) {
    sessionMode = mode;
    modeBadge.textContent = mode;
    modeBadge.className = "badge" + (mode === "meeting" ? " mode-meeting" : "");
    if (mode === "meeting") {
      captionBuffer = "";
      captionText.textContent = "Meeting recording…";
      captionText.classList.remove("empty");
      if (!micUserMuted && !micRecording) {
        startMic();
      }
      startMeetingChunkTimer();
      return;
    }
    stopMeetingChunkTimer();
    if (micRecording && !micUserMuted) {
      stopMic({ sendAudioEnd: true });
    }
    captionBuffer = "";
    captionText.textContent = "Waiting for assistant…";
    captionText.classList.add("empty");
  }

  function sendMode(mode) {
    applyMeetingModeUi(mode);
    sendJson("mode", { mode: mode });
  }

  function handleServerJson(raw) {
    let msg;
    try {
      msg = JSON.parse(raw);
    } catch (_) {
      return;
    }

    switch (msg.type) {
      case "welcome":
        debugLine(
          "Session " +
            msg.payload.session_id +
            (msg.payload.resumed ? " (resumed)" : " (new)"),
          "info"
        );
        break;
      case "caption":
        renderCaption(msg.payload.text, msg.payload.partial);
        break;
      case "user_message":
        appendChatBubble("user", msg.payload.text);
        break;
      case "chat_message":
        renderChatMessage(msg.payload);
        break;
      case "audio_start":
        pendingAudioRate = msg.payload.sample_rate || 24000;
        stopPlayback();
        ensurePlaybackContext(pendingAudioRate);
        if (playbackCtx && playbackCtx.state === "suspended") {
          playbackCtx.resume();
        }
        setPlayback("playing");
        break;
      case "audio_end":
        if (msg.payload && msg.payload.error) {
          debugLine("TTS failed for turn " + msg.payload.turn_id, "error");
          stopPlayback();
        }
        schedulePlaybackIdle();
        if (!micRecording && clientState.capture !== "recording") {
          setTimeout(function () {
            if (
              !micRecording &&
              clientState.playback !== "playing" &&
              clientState.capture !== "recording"
            ) {
              startMic();
            }
          }, 600);
        }
        break;
      case "client_control":
        handleClientControl(msg.payload);
        break;
      case "event":
        if (msg.payload.kind === "session_superseded") {
          debugLine("Session superseded — another device connected", "error");
          setConnStatus("closed");
        } else if (msg.payload.kind === "meeting_started") {
          applyMeetingModeUi("meeting");
          modeSelect.value = "meeting";
          debugLine("Meeting started", "info");
        } else if (msg.payload.kind === "meeting_ended") {
          applyMeetingModeUi("conversation");
          modeSelect.value = "conversation";
          debugLine("Meeting ended — summary processing in background", "info");
        }
        renderEvent(msg.payload);
        break;
      case "notification":
        renderNotification(msg.payload);
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

  function renderChatMessage(payload) {
    if (!payload) return;
    clearConversationStatus();
    const text = (payload.text || "").trim();
    if (!text) {
      if (payload.final !== false) {
        appendChatBubble(
          "assistant",
          "I didn't get a reply — try again?",
          true
        );
      }
      return;
    }
    appendChatBubble("assistant", text, payload.final !== false);
    if (payload.final !== false) {
      captionBuffer = text;
      captionText.textContent = text;
      captionText.classList.remove("empty");
    }
  }

  function renderCaption(text, partial) {
    const chunk = (text || "").trim();
    if (
      sessionMode === "meeting" &&
      !partial &&
      chunk &&
      /^SPEAKER_\d+:/i.test(chunk)
    ) {
      const prev = captionBuffer.trim();
      captionBuffer = prev ? prev + "\n" + chunk : chunk;
      captionText.textContent = captionBuffer;
      captionText.classList.remove("empty");
      return;
    }
    if (partial) {
      if (/…$|\.\.\.$/.test(chunk) || chunk.indexOf("Searching") === 0) {
        captionBuffer = chunk;
        setConversationStatus(chunk);
      } else if (chunk) {
        captionBuffer += chunk;
      }
    } else if (chunk) {
      const prev = captionBuffer.trim();
      if (!prev) {
        captionBuffer = chunk;
      } else if (prev === chunk || prev.endsWith(chunk)) {
        captionBuffer = prev;
      } else if (!prev.includes(chunk)) {
        captionBuffer = prev + " " + chunk;
      }
    }
    if (captionBuffer.trim()) {
      captionText.textContent = captionBuffer;
      captionText.classList.remove("empty");
    } else if (!partial && chunk) {
      captionText.textContent = chunk;
      captionText.classList.remove("empty");
    }
  }

  function appendChatBubble(role, text, isFinal) {
    if (role === "assistant" && isFinal === false) {
      const bubbles = chatThread.querySelectorAll(".bubble.assistant");
      const last = bubbles[bubbles.length - 1];
      if (last) {
        last.querySelector("p").textContent = text;
        return;
      }
    }
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

  function toolEventLabel(kind, summary) {
    if (summary && (kind === "tool_started" || kind === "tool_done")) {
      return compactSummary(
        summary,
        kind === "tool_started" ? "Tool started" : "Tool finished"
      );
    }
    if (kind === "task_step") return compactSummary(summary, "Research in progress");
    if (kind === "task_done") return compactSummary(summary, "Research finished");
    if (kind === "task_error") return compactSummary(summary, "Research failed");
    return compactSummary(summary, kind || "event");
  }

  function setConversationStatus(text) {
    if (!text || !text.trim()) return;
    if (!conversationStatusEl) {
      conversationStatusEl = document.createElement("div");
      conversationStatusEl.className = "bubble status";
      const meta = document.createElement("div");
      meta.className = "meta";
      meta.textContent = "Vayumi";
      const body = document.createElement("p");
      body.className = "status-text";
      conversationStatusEl.appendChild(meta);
      conversationStatusEl.appendChild(body);
      chatThread.appendChild(conversationStatusEl);
    }
    conversationStatusEl.querySelector(".status-text").textContent = text.trim();
    chatThread.scrollTop = chatThread.scrollHeight;
  }

  function clearConversationStatus() {
    if (conversationStatusEl) {
      conversationStatusEl.remove();
      conversationStatusEl = null;
    }
  }

  function renderEvent(event) {
    activityEvents.push(event);
    if (
      event.kind === "tool_started" &&
      event.summary &&
      event.summary.indexOf("Searching") >= 0
    ) {
      setConversationStatus(event.summary);
    }
    renderTaskBoard(activityEvents);
  }

  function renderNotification(payload) {
    if (!payload || !payload.text) return;
    const toast = document.createElement("div");
    toast.className = "notification-toast";
    toast.innerHTML =
      '<span class="notification-label">Update</span>' +
      escapeHtml(payload.text);
    document.body.appendChild(toast);
    requestAnimationFrame(function () {
      toast.classList.add("visible");
    });
    setTimeout(function () {
      toast.classList.remove("visible");
      setTimeout(function () {
        toast.remove();
      }, 300);
    }, 8000);
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
      if (ev.kind === "tool_started" || ev.kind === "tool_done") {
        pill.classList.add(ev.kind === "tool_started" ? "tool-start" : "tool-done");
      } else if (ev.kind === "task_step") {
        pill.classList.add("task-step");
      } else if (ev.kind === "task_done") {
        pill.classList.add("task-done");
      } else if (ev.kind === "task_error") {
        pill.classList.add("task-error");
      }
      const label = toolEventLabel(ev.kind, ev.summary);
      pill.innerHTML =
        '<span class="kind">' +
        escapeHtml(ev.kind) +
        "</span> · " +
        escapeHtml(label);
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
        if (micRecording || micUserMuted) break;
        if (reason === "interrupted" && sessionMode !== "meeting") {
          debugLine("start_capture skipped (interrupt)", "info");
          break;
        }
        if (clientState.playback === "playing" && sessionMode !== "meeting") {
          debugLine("start_capture deferred (playback active)", "info");
          pendingStartCapture = true;
          break;
        }
        pendingStartCapture = false;
        startMic();
        break;
      case "stop_capture":
        if (micRecording) stopMic({ sendAudioEnd: false });
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
    btnMic.textContent = sessionMode === "meeting" ? "Mute" : "Stop mic";
    btnMic.classList.add("mic-active");
    setCapture("recording");
    URL.revokeObjectURL(workletUrl);
  }

  async function stopMic(opts) {
    if (!micRecording) return;
    const sendAudioEnd = !opts || opts.sendAudioEnd !== false;

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

    if (sendAudioEnd) {
      sendJson("audio_end", {});
    } else {
      sendJson("audio_end", { discard: true });
    }
    micRecording = false;
    btnMic.textContent = sessionMode === "meeting" ? "Mute" : "Mic";
    btnMic.classList.remove("mic-active");
    setCapture("idle");

    const meetingRestart =
      sessionMode === "meeting" &&
      !micUserMuted &&
      opts &&
      opts.meetingRestart;
    const meetingAuto =
      sessionMode === "meeting" && !micUserMuted && sendAudioEnd;
    if (meetingRestart || meetingAuto) {
      setTimeout(function () {
        if (sessionMode === "meeting" && !micUserMuted && !micRecording) {
          startMic();
        }
      }, 300);
    }
  }

  function toggleMic() {
    if (micRecording) {
      micUserMuted = true;
      pendingStartCapture = false;
      stopMic();
    } else {
      micUserMuted = false;
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
