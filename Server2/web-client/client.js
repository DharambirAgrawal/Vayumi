(function () {
  "use strict";

  const $ = (id) => document.getElementById(id);

  const statusEl = $("status");
  const tokenEl = $("token");
  const btnConnect = $("btnConnect");
  const btnDisconnect = $("btnDisconnect");
  const logArea = $("logArea");
  const chatInput = $("chatInput");
  const btnSend = $("btnSend");
  const btnRecord = $("btnRecord");
  const btnInterrupt = $("btnInterrupt");

  let ws = null;
  let playbackCtx = null;
  let nextPlayTime = 0;
  let activeSources = [];

  function setStatus(state) {
    statusEl.textContent = state;
    statusEl.className = "status " + state;
    const connected = state === "connected";
    btnConnect.disabled = connected;
    btnDisconnect.disabled = !connected;
    chatInput.disabled = !connected;
    btnSend.disabled = !connected;
    btnRecord.disabled = !connected;
    btnInterrupt.disabled = !connected;
  }

  function appendLog(text, cls) {
    const row = document.createElement("div");
    row.className = "log-entry " + (cls || "info");
    row.textContent = text;
    logArea.appendChild(row);
    logArea.scrollTop = logArea.scrollHeight;
  }

  function sendJson(type, payload) {
    if (!ws || ws.readyState !== WebSocket.OPEN) return;
    const msg = JSON.stringify({ type, payload });
    ws.send(msg);
    appendLog(">>> " + msg, "sent");
  }

  function ensurePlaybackContext(sampleRate) {
    if (!playbackCtx || playbackCtx.sampleRate !== sampleRate) {
      playbackCtx = new AudioContext({ sampleRate: sampleRate });
      nextPlayTime = playbackCtx.currentTime;
    }
    return playbackCtx;
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
  }

  function queuePcmPlayback(arrayBuffer, sampleRate) {
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
    source.connect(ctx.destination);

    const startAt = Math.max(ctx.currentTime, nextPlayTime);
    source.start(startAt);
    nextPlayTime = startAt + buffer.duration;
    activeSources.push(source);
    source.onended = function () {
      activeSources = activeSources.filter(function (s) {
        return s !== source;
      });
    };
  }

  function connect() {
    const token = tokenEl.value.trim();
    if (!token) {
      appendLog("Error: enter a token", "error");
      return;
    }

    const proto = location.protocol === "https:" ? "wss:" : "ws:";
    const url = proto + "//" + location.host + "/ws/v1/session?token=" + encodeURIComponent(token);

    setStatus("connecting");
    appendLog("Connecting to " + url + " ...");

    ws = new WebSocket(url);
    ws.binaryType = "arraybuffer";

    ws.onopen = function () {
      setStatus("connected");
      appendLog("WebSocket open");
      sendJson("hello", {
        client: "web",
        capabilities: { aec: false, vad: false, wake: false },
      });
    };

    ws.onmessage = function (ev) {
      if (typeof ev.data === "string") {
        appendLog("<<< " + ev.data, "recv");
        renderServerMessage(ev.data);
      } else if (ev.data instanceof ArrayBuffer) {
        const rate = pendingAudioRate || 16000;
        queuePcmPlayback(ev.data, rate);
        appendLog("<<< binary TTS frame: " + ev.data.byteLength + " bytes", "recv");
      }
    };

    ws.onclose = function (ev) {
      setStatus("closed");
      stopPlayback();
      appendLog("WebSocket closed: code=" + ev.code + " reason=" + (ev.reason || "(none)"));
      ws = null;
    };

    ws.onerror = function () {
      appendLog("WebSocket error", "error");
    };
  }

  let pendingAudioRate = 16000;

  function disconnect() {
    if (ws) ws.close();
  }

  function sendChat() {
    const text = chatInput.value.trim();
    if (!text) return;
    sendJson("chat", { text: text });
    chatInput.value = "";
  }

  function sendInterrupt() {
    stopPlayback();
    sendJson("interrupt", { source: "button" });
    appendLog("Interrupt sent", "info");
  }

  function renderServerMessage(raw) {
    let msg;
    try {
      msg = JSON.parse(raw);
    } catch (_) {
      return;
    }
    if (msg.type === "caption") {
      const marker = msg.payload.partial ? "caption chunk" : "caption final";
      appendLog(marker + ": " + msg.payload.text, "caption");
    }
    if (msg.type === "audio_start") {
      pendingAudioRate = msg.payload.sample_rate || 16000;
      stopPlayback();
      appendLog("TTS stream start turn_id=" + msg.payload.turn_id, "info");
    }
    if (msg.type === "audio_end") {
      appendLog("TTS stream end turn_id=" + msg.payload.turn_id, "info");
    }
  }

  async function recordOneSecond() {
    btnRecord.disabled = true;
    appendLog("Requesting microphone...");

    let stream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          channelCount: 1,
          sampleRate: 16000,
        },
      });
    } catch (err) {
      appendLog("Mic error: " + err.message, "error");
      btnRecord.disabled = false;
      return;
    }

    const audioCtx = new AudioContext({ sampleRate: 16000 });
    const source = audioCtx.createMediaStreamSource(stream);

    const workletCode = `
      class PcmCapture extends AudioWorkletProcessor {
        constructor() {
          super();
          this._buf = [];
        }
        process(inputs) {
          const ch = inputs[0][0];
          if (ch) {
            const i16 = new Int16Array(ch.length);
            for (let i = 0; i < ch.length; i++) {
              const s = Math.max(-1, Math.min(1, ch[i]));
              i16[i] = s < 0 ? s * 0x8000 : s * 0x7FFF;
            }
            this.port.postMessage(i16.buffer, [i16.buffer]);
          }
          return true;
        }
      }
      registerProcessor("pcm-capture", PcmCapture);
    `;

    const blob = new Blob([workletCode], { type: "application/javascript" });
    const workletUrl = URL.createObjectURL(blob);

    try {
      await audioCtx.audioWorklet.addModule(workletUrl);
    } catch (err) {
      appendLog("AudioWorklet error: " + err.message, "error");
      stream.getTracks().forEach((t) => t.stop());
      await audioCtx.close();
      btnRecord.disabled = false;
      return;
    }

    const node = new AudioWorkletNode(audioCtx, "pcm-capture");
    source.connect(node);
    node.connect(audioCtx.destination);

    sendJson("audio_start", { sample_rate: 16000, format: "pcm_s16le" });
    appendLog("Recording 1 second...");

    const chunks = [];
    node.port.onmessage = function (ev) {
      if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(ev.data);
      }
      chunks.push(ev.data);
    };

    await new Promise((r) => setTimeout(r, 1000));

    node.port.onmessage = null;
    source.disconnect();
    node.disconnect();
    stream.getTracks().forEach((t) => t.stop());
    await audioCtx.close();
    URL.revokeObjectURL(workletUrl);

    sendJson("audio_end", {});

    const totalBytes = chunks.reduce((s, c) => s + c.byteLength, 0);
    appendLog("Sent " + totalBytes + " bytes of PCM audio");

    btnRecord.disabled = false;
  }

  btnConnect.addEventListener("click", connect);
  btnDisconnect.addEventListener("click", disconnect);
  btnSend.addEventListener("click", sendChat);
  btnInterrupt.addEventListener("click", sendInterrupt);
  chatInput.addEventListener("keydown", function (e) {
    if (e.key === "Enter") sendChat();
  });
  btnRecord.addEventListener("click", recordOneSecond);

  setStatus("closed");
  appendLog("Vayumi dev client ready. Enter a token and connect.");
})();
