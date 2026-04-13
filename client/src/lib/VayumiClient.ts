/**
 * Main VayumiClient - WebSocket protocol handler and state management
 */
import {
  ConnectionState,
  Mode,
  ClientType,
  AudioConfig,
  ChatMessage,
  ChatResponse,
  AuthResponse,
  AuthUser,
  StateChangeCallback,
  EventCallback,
} from './types';

interface WSMessage {
  type: string;
  [key: string]: any;
}

class VayumiClient {
  private ws: WebSocket | null = null;
  private serverUrl: string = '';
  private sessionId: string = '';
  private connectionState: ConnectionState = 'disconnected';
  private mode: Mode = 'conversation';
  private reconnectAttempts: number = 0;
  private maxReconnectAttempts: number = 10;
  private reconnectDelay: number = 1000;
  private pendingMessageWaiters: Array<{
    predicate: (message: WSMessage) => boolean;
    resolve: (message: WSMessage) => void;
    reject: (error: Error) => void;
    timeoutId: number;
  }> = [];

  // Event listeners
  private stateChangeCallbacks: Set<StateChangeCallback> = new Set();
  private eventListeners: Map<string, Set<EventCallback<any>>> = new Map();
  private chatResponseCallbacks: Set<EventCallback<any>> = new Set();

  // Audio resources
  private audioContext: AudioContext | null = null;
  private ttsAudioContext: AudioContext | null = null;
  private mediaStream: MediaStream | null = null;
  private audioWorklet: AudioWorkletNode | null = null;
  private sourceNode: MediaStreamAudioSourceNode | null = null;
  private scriptProcessor: ScriptProcessorNode | null = null;
  private zeroGainNode: GainNode | null = null;
  private ttsPlaybackTime: number = 0;
  private activeTTSSources: Set<AudioBufferSourceNode> = new Set();
  private dropTTSUntilNextStream: boolean = false;

  private vadEnabled: boolean = true;
  private isStreamingAudio: boolean = false;
  private lastSpeechAt: number = 0;
  private silenceTimeoutMs: number = 1200;
  private speechThreshold: number = 0.01;
  private serverSideVoiceEnabled: boolean = true;
  private authToken: string | null = null;

  /**
   * Create a new VayumiClient instance
   */
  constructor() {
    this.setupEventListeners();
  }

  private setupEventListeners(): void {
    // Initialize event listener maps
    const eventTypes = [
      'wake_word_detected',
      'wake_word_required',
      'wake_word_status',
      'wake_word_debug',
      'vad_speech_start',
      'vad_speech_end',
      'transcription_partial',
      'transcription_final',
      'agent_thinking',
      'agent_speaking',
      'agent_done',
      'interrupt_ack',
      'tts_stream_start',
      'tts_stream_end',
      'tts_chunk',
      'mode_changed',
      'diarization_segment',
      'speaker_identified',
      'error',
    ];

    eventTypes.forEach(type => {
      this.eventListeners.set(type, new Set());
    });
  }

  /**
   * Connect to the Vayumi server
   */
  async connect(serverUrl: string, _options?: { clientType?: ClientType }): Promise<void> {
    this.serverUrl = serverUrl;
    this.setConnectionState('connecting');

    return new Promise((resolve, reject) => {
      try {
        const baseWsUrl = serverUrl.replace(/^http/, 'ws').replace(/\/$/, '') + '/ws/audio';
        const wsUrl = this.authToken
          ? `${baseWsUrl}?token=${encodeURIComponent(this.authToken)}`
          : baseWsUrl;
        this.ws = new WebSocket(wsUrl);
        this.ws.binaryType = 'arraybuffer';

        this.ws.onopen = async () => {
          console.log('[Vayumi] WebSocket connected');
          await this.handleConnection();
          resolve();
        };

        this.ws.onmessage = (event) => this.handleMessage(event);
        this.ws.onerror = (error) => {
          console.error('[Vayumi] WebSocket error:', error);
          reject(error);
        };
        this.ws.onclose = () => this.handleDisconnection();
      } catch (error) {
        reject(error);
      }
    });
  }

  /**
   * Disconnect from server
   */
  disconnect(reason?: string): void {
    console.log(`[Vayumi] Disconnecting (reason: ${reason || 'user'})`);
    this.reconnectAttempts = this.maxReconnectAttempts; // Disable auto-reconnect
    this.clearPendingWaiters(reason || 'user_disconnect');
    this.stopMicrophone();
    
    if (this.ws) {
      this.ws.close(1000, reason || 'user_disconnect');
    }
  }

  setServerUrl(serverUrl: string): void {
    this.serverUrl = serverUrl;
  }

  setAuthToken(token: string | null): void {
    this.authToken = token;
  }

  getAuthToken(): string | null {
    return this.authToken;
  }

  async register(email: string, password: string, name?: string): Promise<AuthResponse> {
    if (!this.serverUrl) {
      throw new Error('Server URL is not set. Connect once or set VITE_SERVER_URL before auth calls.');
    }

    const response = await fetch(`${this.serverUrl.replace(/\/$/, '')}/auth/register`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ email, password, name }),
    });

    if (!response.ok) {
      const body = await response.text();
      throw new Error(`Register failed: ${response.status} ${body}`);
    }

    const payload = (await response.json()) as AuthResponse;
    this.setAuthToken(payload.access_token);
    return payload;
  }

  async login(email: string, password: string): Promise<AuthResponse> {
    if (!this.serverUrl) {
      throw new Error('Server URL is not set. Connect once or set VITE_SERVER_URL before auth calls.');
    }

    const response = await fetch(`${this.serverUrl.replace(/\/$/, '')}/auth/login`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ email, password }),
    });

    if (!response.ok) {
      const body = await response.text();
      throw new Error(`Login failed: ${response.status} ${body}`);
    }

    const payload = (await response.json()) as AuthResponse;
    this.setAuthToken(payload.access_token);
    return payload;
  }

  async me(): Promise<AuthUser> {
    if (!this.serverUrl) {
      throw new Error('Server URL is not set. Connect once or set VITE_SERVER_URL before auth calls.');
    }
    if (!this.authToken) {
      throw new Error('Missing auth token');
    }

    const response = await fetch(`${this.serverUrl.replace(/\/$/, '')}/auth/me`, {
      method: 'GET',
      headers: {
        Authorization: `Bearer ${this.authToken}`,
      },
    });

    if (!response.ok) {
      const body = await response.text();
      throw new Error(`Auth me failed: ${response.status} ${body}`);
    }

    return (await response.json()) as AuthUser;
  }

  /**
   * Handle initial WebSocket connection
   */
  private async handleConnection(): Promise<void> {
    // Receive hello message
    const hello = await this.waitForMessage((message) => message.type === 'hello');
    console.log('[Vayumi] Received hello:', hello);

    this.sessionId = hello.session_id;

    // Send client_ready
    const audioConfig: AudioConfig = {
      sample_rate: 16000,
      channels: 1,
      bit_depth: 16,
    };

    await this.sendJSON({
      type: 'client_ready',
      client_type: 'web',
      capabilities: ['vad', 'wake_word'],
      audio_config: audioConfig,
    });

    // Wait for session_started
    const sessionStarted = await this.waitForMessage((message) => message.type === 'session_started');
    console.log('[Vayumi] Session started:', sessionStarted);

    // Prompt mic permission and start the continuous server-side voice stream.
    // Connection should remain usable for typed chat even if mic permission is denied.
    try {
      await this.startMicrophone();
    } catch (error) {
      this.emitEvent('error', {
        code: 'microphone_unavailable',
        message: String(error),
        fatal: false,
      });
      this.emitEvent('wake_word_status', 'mic-unavailable');
    }

    this.setConnectionState('connected_idle');
    this.reconnectAttempts = 0;
  }

  /**
   * Handle WebSocket messages
   */
  private handleMessage(event: MessageEvent): void {
    if (typeof event.data === 'string') {
      try {
        const message: WSMessage = JSON.parse(event.data);
        this.resolvePendingWaiters(message);
        this.processMessage(message);
      } catch (error) {
        console.error('[Vayumi] JSON parse error:', error);
      }
    } else if (event.data instanceof ArrayBuffer) {
      // Binary audio data (TTS)
      console.log('[Vayumi] Received audio chunk:', event.data.byteLength, 'bytes');
      this.playTTSChunk(event.data);
      this.emitEvent('tts_chunk', event.data);
    } else if (event.data instanceof Blob) {
      void event.data.arrayBuffer().then((buffer) => {
        console.log('[Vayumi] Received audio blob:', buffer.byteLength, 'bytes');
        this.playTTSChunk(buffer);
        this.emitEvent('tts_chunk', buffer);
      }).catch((error) => {
        console.error('[Vayumi] Failed to decode TTS blob:', error);
      });
    }
  }

  /**
   * Process a message from the server
   */
  private processMessage(message: WSMessage): void {
    const { type } = message;
    if (type !== 'hello' && type !== 'session_started') {
      console.log('[Vayumi] Message:', type);
    }

    switch (type) {
      case 'hello':
      case 'session_started':
        // Consumed by handshake flow in handleConnection.
        break;

      case 'vad_speech_start':
        this.setConnectionState('streaming_audio');
        this.emitEvent('vad_speech_start', undefined);
        break;

      case 'vad_speech_end':
        this.setConnectionState('waiting_response');
        this.emitEvent('vad_speech_end', undefined);
        break;

      case 'transcription_partial':
        this.emitEvent('transcription_partial', message.text);
        break;

      case 'transcription_final':
        // Current backend sends final transcript without downstream agent events,
        // so move back to idle after utterance is finalized.
        this.setConnectionState('connected_idle');
        this.emitEvent('transcription_final', message);
        break;

      case 'wake_word_detected':
        this.setConnectionState('wake_detected');
        this.emitEvent('wake_word_detected', message.confidence ?? 0.9);
        break;

      case 'wake_word_status':
        this.emitEvent('wake_word_status', message.status || 'unknown');
        break;

      case 'wake_word_required':
        this.emitEvent('wake_word_required', message);
        this.emitEvent('wake_word_status', 'waiting-for-vayumi');
        break;

      case 'wake_window_opened':
        this.emitEvent('wake_word_status', 'command-window-open');
        break;

      case 'wake_window_closed':
        this.emitEvent('wake_word_status', 'sleeping');
        break;

      case 'agent_thinking':
        this.setConnectionState('waiting_response');
        this.emitEvent('agent_thinking', undefined);
        break;

      case 'agent_response_start':
        this.setConnectionState('ai_speaking');
        this.emitEvent('agent_speaking', message.response_id);
        break;

      case 'tts_stream_start':
        this.dropTTSUntilNextStream = false;
        this.stopAllTTSPlayback();
        this.resetTTSPlayback();
        this.emitEvent('tts_stream_start', message);
        break;

      case 'tts_stream_end':
        this.emitEvent('tts_stream_end', message);
        break;

      case 'agent_response_end':
        this.emitEvent('agent_done', message.response_id);
        break;

      case 'chatbot_response':
        this.chatResponseCallbacks.forEach(cb => cb({
          text: message.text,
          spoken: message.spoken,
          response_id: message.response_id,
        }));
        break;

      case 'interrupt_ack':
        this.dropTTSUntilNextStream = true;
        this.stopAllTTSPlayback();
        this.emitEvent('interrupt_ack', message);
        this.setConnectionState('connected_idle');
        break;

      case 'mode_changed':
        this.mode = message.mode;
        this.emitEvent('mode_changed', { mode: message.mode, features: message.features });
        break;

      case 'diarization_segment':
        this.emitEvent('diarization_segment', message);
        break;

      case 'speaker_identified':
        this.emitEvent('speaker_identified', message);
        break;

      case 'error':
        this.emitEvent('error', {
          code: message.code,
          message: message.message,
          fatal: message.fatal,
        });
        if (message.fatal) {
          this.disconnect('fatal_error');
        }
        break;

      case 'pong':
        // Keepalive response
        break;

      default:
        console.warn('[Vayumi] Unknown message type:', type);
    }
  }

  /**
   * Handle WebSocket disconnection
   */
  private handleDisconnection(): void {
    console.log('[Vayumi] WebSocket disconnected');
    this.clearPendingWaiters('websocket_disconnected');
    this.stopMicrophone();
    this.setConnectionState('disconnected');

    // Attempt auto-reconnect
    if (this.reconnectAttempts < this.maxReconnectAttempts) {
      this.reconnectAttempts++;
      const delay = Math.min(this.reconnectDelay * this.reconnectAttempts, 30000);
      console.log(`[Vayumi] Attempting reconnect in ${delay}ms...`);
      setTimeout(() => {
        this.connect(this.serverUrl).catch(err => {
          console.error('[Vayumi] Reconnect failed:', err);
        });
      }, delay);
    }
  }

  // ============================================================================
  // WebSocket Utilities
  // ============================================================================

  private async sendJSON(data: any): Promise<void> {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
      throw new Error('WebSocket not connected');
    }
    this.ws.send(JSON.stringify(data));
  }

  private async sendBinary(data: Uint8Array): Promise<void> {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
      throw new Error('WebSocket not connected');
    }
    this.ws.send(data.buffer.slice(data.byteOffset, data.byteOffset + data.byteLength));
  }

  private waitForMessage(predicate: (message: WSMessage) => boolean, timeoutMs: number = 10000): Promise<WSMessage> {
    return new Promise((resolve, reject) => {
      const timeoutId = window.setTimeout(() => {
        this.pendingMessageWaiters = this.pendingMessageWaiters.filter((waiter) => waiter.resolve !== resolve);
        reject(new Error('Timed out waiting for websocket message'));
      }, timeoutMs);

      this.pendingMessageWaiters.push({ predicate, resolve, reject, timeoutId });
    });
  }

  private resolvePendingWaiters(message: WSMessage): void {
    if (this.pendingMessageWaiters.length === 0) {
      return;
    }

    const remaining: typeof this.pendingMessageWaiters = [];
    for (const waiter of this.pendingMessageWaiters) {
      if (waiter.predicate(message)) {
        window.clearTimeout(waiter.timeoutId);
        waiter.resolve(message);
      } else {
        remaining.push(waiter);
      }
    }
    this.pendingMessageWaiters = remaining;
  }

  private clearPendingWaiters(reason: string): void {
    for (const waiter of this.pendingMessageWaiters) {
      window.clearTimeout(waiter.timeoutId);
      waiter.reject(new Error(reason));
    }
    this.pendingMessageWaiters = [];
  }

  // ============================================================================
  // Audio Control
  // ============================================================================

  async startMicrophone(): Promise<void> {
    try {
      if (this.mediaStream) {
        return;
      }

      console.log('[Vayumi] Starting microphone...');
      this.mediaStream = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: false,
        },
      });

      if (!this.audioContext) {
        this.audioContext = new (window.AudioContext || (window as any).webkitAudioContext)();
      }

      if (this.audioContext.state === 'suspended') {
        await this.audioContext.resume();
      }

      this.sourceNode = this.audioContext.createMediaStreamSource(this.mediaStream);
      this.scriptProcessor = this.audioContext.createScriptProcessor(4096, 1, 1);
      this.zeroGainNode = this.audioContext.createGain();
      this.zeroGainNode.gain.value = 0;

      this.scriptProcessor.onaudioprocess = (event: AudioProcessingEvent) => {
        const input = event.inputBuffer.getChannelData(0);
        const energy = this.calculateEnergy(input);
        const now = Date.now();

        if (energy > this.speechThreshold) {
          this.lastSpeechAt = now;
        }

        if (this.serverSideVoiceEnabled && !this.isStreamingAudio) {
          this.safeBeginStreaming('manual');
        }

        if (!this.isStreamingAudio) {
          return;
        }

        // Send 16kHz mono PCM16 chunks to server.
        const downsampled = this.downsampleTo16k(input, this.audioContext?.sampleRate || 16000);
        const pcmChunk = this.floatTo16BitPCM(downsampled);
        if (pcmChunk.byteLength > 0) {
          this.safeSendBinary(pcmChunk);
        }

        if (!this.serverSideVoiceEnabled && this.vadEnabled && now - this.lastSpeechAt > this.silenceTimeoutMs) {
          this.safeEndStreaming('vad_silence');
        }
      };

      this.sourceNode.connect(this.scriptProcessor);
      this.scriptProcessor.connect(this.zeroGainNode);
      this.zeroGainNode.connect(this.audioContext.destination);

      if (this.serverSideVoiceEnabled) {
        this.emitEvent('wake_word_status', 'server-side-vad');
        this.emitEvent('wake_word_debug', 'continuous-mic-stream');
        this.safeBeginStreaming('manual');
      }

      console.log('[Vayumi] Microphone ready');
    } catch (error) {
      console.error('[Vayumi] Microphone error:', error);
      throw error;
    }
  }

  stopMicrophone(): void {
    this.isStreamingAudio = false;

    if (this.scriptProcessor) {
      this.scriptProcessor.disconnect();
      this.scriptProcessor.onaudioprocess = null;
      this.scriptProcessor = null;
    }

    if (this.sourceNode) {
      this.sourceNode.disconnect();
      this.sourceNode = null;
    }

    if (this.mediaStream) {
      this.mediaStream.getTracks().forEach(track => track.stop());
      this.mediaStream = null;
    }

    if (this.audioWorklet) {
      this.audioWorklet.disconnect();
      this.audioWorklet = null;
    }

    if (this.zeroGainNode) {
      this.zeroGainNode.disconnect();
      this.zeroGainNode = null;
    }

    if (this.audioContext) {
      void this.audioContext.close();
      this.audioContext = null;
    }

    if (this.ttsAudioContext) {
      void this.ttsAudioContext.close();
      this.ttsAudioContext = null;
    }

    this.ttsPlaybackTime = 0;
  }

  setVADEnabled(enabled: boolean): void {
    this.vadEnabled = enabled;
    console.log(`[Vayumi] VAD ${enabled ? 'enabled' : 'disabled'}`);
  }

  // ============================================================================
  // Audio Streaming
  // ============================================================================

  private async beginStreaming(trigger: 'wake_word' | 'manual' | 'meeting_mode'): Promise<void> {
    if (this.isStreamingAudio) {
      return;
    }

    this.isStreamingAudio = true;
    this.lastSpeechAt = Date.now();
    await this.sendJSON({
      type: 'audio_stream_start',
      trigger,
      timestamp: Date.now() / 1000,
    });
  }

  private async endStreaming(reason: 'vad_silence' | 'manual' | 'timeout'): Promise<void> {
    if (!this.isStreamingAudio) {
      return;
    }

    this.isStreamingAudio = false;
    await this.sendJSON({
      type: 'audio_stream_end',
      reason,
      duration_ms: 0,
    });
  }

  private safeBeginStreaming(trigger: 'wake_word' | 'manual' | 'meeting_mode'): void {
    void this.beginStreaming(trigger).catch((error) => {
      console.error('[Vayumi] beginStreaming failed:', error);
      this.emitEvent('error', {
        code: 'audio_stream_start_failed',
        message: String(error),
        fatal: false,
      });
      this.isStreamingAudio = false;
    });
  }

  private safeEndStreaming(reason: 'vad_silence' | 'manual' | 'timeout'): void {
    void this.endStreaming(reason).catch((error) => {
      console.error('[Vayumi] endStreaming failed:', error);
      this.emitEvent('error', {
        code: 'audio_stream_end_failed',
        message: String(error),
        fatal: false,
      });
      this.isStreamingAudio = false;
    });
  }

  private safeSendBinary(chunk: Uint8Array): void {
    void this.sendBinary(chunk).catch((error) => {
      console.error('[Vayumi] sendBinary failed:', error);
      this.emitEvent('error', {
        code: 'audio_chunk_send_failed',
        message: String(error),
        fatal: false,
      });
      this.isStreamingAudio = false;
    });
  }

  private calculateEnergy(input: Float32Array): number {
    let sumSquares = 0;
    for (let i = 0; i < input.length; i++) {
      const sample = input[i];
      sumSquares += sample * sample;
    }
    return Math.sqrt(sumSquares / input.length);
  }

  private downsampleTo16k(buffer: Float32Array, sampleRate: number): Float32Array {
    if (sampleRate === 16000) {
      return buffer;
    }

    const ratio = sampleRate / 16000;
    const newLength = Math.max(1, Math.floor(buffer.length / ratio));
    const result = new Float32Array(newLength);

    for (let i = 0; i < newLength; i++) {
      const idx = Math.floor(i * ratio);
      result[i] = buffer[idx] ?? 0;
    }

    return result;
  }

  private floatTo16BitPCM(float32: Float32Array): Uint8Array {
    const buffer = new ArrayBuffer(float32.length * 2);
    const view = new DataView(buffer);

    for (let i = 0; i < float32.length; i++) {
      const sample = Math.max(-1, Math.min(1, float32[i]));
      view.setInt16(i * 2, sample < 0 ? sample * 0x8000 : sample * 0x7fff, true);
    }

    return new Uint8Array(buffer);
  }

  private async ensureTTSPlaybackContext(): Promise<AudioContext> {
    if (this.audioContext && this.audioContext.state !== 'closed') {
      if (this.audioContext.state === 'suspended') {
        await this.audioContext.resume();
      }
      return this.audioContext;
    }

    if (!this.ttsAudioContext) {
      this.ttsAudioContext = new (window.AudioContext || (window as any).webkitAudioContext)();
    }

    if (this.ttsAudioContext.state === 'suspended') {
      await this.ttsAudioContext.resume();
    }

    return this.ttsAudioContext;
  }

  private resetTTSPlayback(): void {
    this.ttsPlaybackTime = 0;
  }

  private stopAllTTSPlayback(): void {
    this.activeTTSSources.forEach((source) => {
      try {
        source.stop(0);
      } catch {
        // Source may already be stopped.
      }
    });
    this.activeTTSSources.clear();
    this.ttsPlaybackTime = 0;
  }

  private async playTTSChunk(chunk: ArrayBuffer): Promise<void> {
    try {
      if (this.dropTTSUntilNextStream) {
        return;
      }

      const context = await this.ensureTTSPlaybackContext();
      const int16 = new Int16Array(chunk);
      if (int16.length === 0) {
        return;
      }

      const float32 = new Float32Array(int16.length);
      for (let i = 0; i < int16.length; i += 1) {
        float32[i] = int16[i] / 32768;
      }

      const audioBuffer = context.createBuffer(1, float32.length, 16000);
      audioBuffer.copyToChannel(float32, 0);

      const source = context.createBufferSource();
      source.buffer = audioBuffer;
      source.connect(context.destination);

      // Cap playback lead time so interrupt can cut in quickly even under bursty chunk delivery.
      const minLead = 0.01;
      const maxLead = 0.08;
      let startAt = Math.max(context.currentTime + minLead, this.ttsPlaybackTime || context.currentTime);
      if (startAt - context.currentTime > maxLead) {
        startAt = context.currentTime + minLead;
      }

      source.onended = () => {
        this.activeTTSSources.delete(source);
      };
      this.activeTTSSources.add(source);
      source.start(startAt);
      this.ttsPlaybackTime = startAt + audioBuffer.duration;
    } catch (error) {
      console.error('[Vayumi] TTS playback failed:', error);
      this.emitEvent('error', {
        code: 'tts_playback_failed',
        message: String(error),
        fatal: false,
      });
    }
  }

  async triggerManualPushToTalk(): Promise<void> {
    console.log('[Vayumi] Push to talk triggered');
    await this.beginStreaming('manual');
  }

  async releaseManualPushToTalk(): Promise<void> {
    console.log('[Vayumi] Push to talk released');
    await this.endStreaming('manual');
  }

  async interrupt(): Promise<void> {
    console.log('[Vayumi] Interrupt sent');
    this.setConnectionState('interrupting');
    await this.sendJSON({
      type: 'interrupt',
      trigger: 'wake_word',
      timestamp: Date.now() / 1000,
    });
  }

  // ============================================================================
  // Mode & State
  // ============================================================================

  async switchMode(mode: Mode): Promise<void> {
    console.log(`[Vayumi] Switching to mode: ${mode}`);
    await this.sendJSON({
      type: 'mode_switch',
      mode,
      requested_by: 'ui_button',
    });
  }

  getCurrentMode(): Mode {
    return this.mode;
  }

  getConnectionState(): ConnectionState {
    return this.connectionState;
  }

  getSessionId(): string {
    return this.sessionId;
  }

  // ============================================================================
  // Chatbot
  // ============================================================================

  async sendChatMessage(message: ChatMessage): Promise<ChatResponse | null> {
    console.log('[Vayumi] Sending chat message:', message);

    const payload = {
      type: 'chatbot_message',
      content_type: 'text',
      text: message.text || '',
      attachments: message.attachments || [],
      respond_via: message.respond_via || 'chat_only',
      interrupt_policy: message.interrupt_policy || 'queue',
    };

    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      await this.sendJSON(payload);
      return null;
    }

    return this.sendChatMessageHttp(message);
  }

  private async sendChatMessageHttp(message: ChatMessage): Promise<ChatResponse> {
    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
    };
    if (this.authToken) {
      headers.Authorization = `Bearer ${this.authToken}`;
    }

    const response = await fetch(`${this.serverUrl.replace(/\/$/, '')}/chat`, {
      method: 'POST',
      headers,
      body: JSON.stringify({
        text: message.text || '',
        attachments: message.attachments || [],
        respond_via: message.respond_via || 'chat_only',
        interrupt_policy: message.interrupt_policy || 'queue',
        session_id: this.sessionId || undefined,
      }),
    });

    if (!response.ok) {
      throw new Error(`Chat HTTP fallback failed: ${response.status} ${response.statusText}`);
    }

    const payload = await response.json();
    return {
      text: payload.text || '',
      spoken: Boolean(payload.spoken),
      response_id: payload.response_id || '',
    };
  }

  onChatResponse(cb: EventCallback<any>): () => void {
    this.chatResponseCallbacks.add(cb);
    return () => this.chatResponseCallbacks.delete(cb);
  }

  // ============================================================================
  // Event Management
  // ============================================================================

  on<T>(event: string, cb: EventCallback<T>): () => void {
    if (!this.eventListeners.has(event)) {
      this.eventListeners.set(event, new Set());
    }
    const callbacks = this.eventListeners.get(event)!;
    callbacks.add(cb);
    return () => callbacks.delete(cb);
  }

  private emitEvent(event: string, data: any): void {
    const callbacks = this.eventListeners.get(event);
    if (callbacks) {
      callbacks.forEach(cb => cb(data));
    }
  }

  onStateChange(cb: StateChangeCallback): () => void {
    this.stateChangeCallbacks.add(cb);
    return () => this.stateChangeCallbacks.delete(cb);
  }

  private setConnectionState(state: ConnectionState): void {
    if (state !== this.connectionState) {
      console.log(`[Vayumi] State: ${this.connectionState} → ${state}`);
      this.connectionState = state;
      this.stateChangeCallbacks.forEach(cb => cb(state));
    }
  }
}

// Export singleton instance
export const vayumiClient = new VayumiClient();
export default VayumiClient;
