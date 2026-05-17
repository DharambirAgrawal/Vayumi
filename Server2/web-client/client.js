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

  let ws = null;

  function setStatus(state) {
    statusEl.textContent = state;
    statusEl.className = "status " + state;
    const connected = state === "connected";
    btnConnect.disabled = connected;
    btnDisconnect.disabled = !connected;
    chatInput.disabled = !connected;
    btnSend.disabled = !connected;
    btnRecord.disabled = !connected;
  }

  function appendLog(text, cls) {
    const el = document.createElement("div");
    el.className = "log-entry " + (cls || "info");
    el.textContent = text;
    logArea.appendChild(el);
    logArea.scrollTop = logArea.scrollHeight;
  }

  function sendJson(type, payload) {
    if (!ws || ws.readyState !== WebSocket.OPEN) return;
    const msg = JSON.stringify({ type, payload });
    ws.send(msg);
    appendLog(">>> " + msg, "sent");
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
      } else if (ev.data instanceof Blob) {
        ev.data.arrayBuffer().then(function (buf) {
          appendLog("<<< binary frame received: " + buf.byteLength + " bytes", "recv");
        });
      }
    };

    ws.onclose = function (ev) {
      setStatus("closed");
      appendLog("WebSocket closed: code=" + ev.code + " reason=" + (ev.reason || "(none)"));
      ws = null;
    };

    ws.onerror = function () {
      appendLog("WebSocket error", "error");
    };
  }

  function disconnect() {
    if (ws) ws.close();
  }

  function sendChat() {
    const text = chatInput.value.trim();
    if (!text) return;
    sendJson("chat", { text: text });
    chatInput.value = "";
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
  chatInput.addEventListener("keydown", function (e) {
    if (e.key === "Enter") sendChat();
  });
  btnRecord.addEventListener("click", recordOneSecond);

  setStatus("closed");
  appendLog("Vayumi dev client ready. Enter a token and connect.");
})();
