import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import VayumiClient from './VayumiClient';

class FakeWebSocket {
  static CONNECTING = 0;
  static OPEN = 1;
  static CLOSING = 2;
  static CLOSED = 3;
  static instances: FakeWebSocket[] = [];

  url: string;
  readyState = FakeWebSocket.CONNECTING;
  binaryType = 'blob';
  sent: Array<string | ArrayBuffer> = [];
  closeArgs: { code?: number; reason?: string } | null = null;

  onopen: ((event?: any) => void) | null = null;
  onmessage: ((event: { data: string | ArrayBuffer }) => void) | null = null;
  onerror: ((event?: any) => void) | null = null;
  onclose: ((event?: any) => void) | null = null;

  constructor(url: string) {
    this.url = url;
    FakeWebSocket.instances.push(this);
    queueMicrotask(() => {
      this.readyState = FakeWebSocket.OPEN;
      this.onopen?.({});
    });
  }

  send(data: string | ArrayBuffer): void {
    this.sent.push(data);
  }

  close(code?: number, reason?: string): void {
    this.closeArgs = { code, reason };
    this.readyState = FakeWebSocket.CLOSED;
    this.onclose?.({});
  }

  emitJSON(message: Record<string, unknown>): void {
    this.onmessage?.({ data: JSON.stringify(message) });
  }
}

describe('VayumiClient', () => {
  beforeEach(() => {
    FakeWebSocket.instances = [];
    vi.stubGlobal('window', globalThis);
    vi.stubGlobal('WebSocket', FakeWebSocket);
    vi.stubGlobal('fetch', vi.fn());
    Object.defineProperty(globalThis, 'navigator', {
      value: {
        mediaDevices: {
          getUserMedia: vi.fn().mockRejectedValue(new Error('mic denied')),
        },
      },
      configurable: true,
      writable: true,
    });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it('connects through the websocket handshake and sends client_ready with auth token', async () => {
    const client = new VayumiClient();
    client.setAuthToken('token-123');

    const states: string[] = [];
    client.onStateChange((state) => states.push(state));

    const connectPromise = client.connect('http://localhost:8000');
    await vi.waitFor(() => expect(FakeWebSocket.instances).toHaveLength(1));

    const socket = FakeWebSocket.instances[0];
    expect(socket.url).toBe('ws://localhost:8000/ws/audio?token=token-123');

    socket.emitJSON({ type: 'hello', session_id: 'session-1' });
    await vi.waitFor(() => expect(socket.sent).toHaveLength(1));
    expect(JSON.parse(String(socket.sent[0]))).toMatchObject({
      type: 'client_ready',
      client_type: 'web',
      capabilities: ['vad', 'wake_word'],
    });

    socket.emitJSON({ type: 'session_started', session_id: 'session-1' });
    await connectPromise;

    expect(client.getSessionId()).toBe('session-1');
    expect(client.getConnectionState()).toBe('connected_idle');
    expect(states).toContain('connecting');
    expect(states).toContain('connected_idle');
  });

  it('sends websocket chat payloads with attachments when connected', async () => {
    const client = new VayumiClient() as any;
    const socket = new FakeWebSocket('ws://localhost:8000/ws/audio');
    socket.readyState = FakeWebSocket.OPEN;
    client.ws = socket;

    const result = await client.sendChatMessage({
      text: 'check these',
      attachments: [
        { type: 'link', url: 'https://example.com' },
        { type: 'image', url: 'https://example.com/image.png' },
        { type: 'video', url: 'https://example.com/video.mp4' },
      ],
      respond_via: 'chat_only',
      interrupt_policy: 'queue',
    });

    expect(result).toBeNull();
    expect(JSON.parse(String(socket.sent[0]))).toMatchObject({
      type: 'chatbot_message',
      text: 'check these',
      interrupt_policy: 'queue',
    });
    expect(JSON.parse(String(socket.sent[0])).attachments).toHaveLength(3);
  });

  it('falls back to HTTP chat when websocket is unavailable and keeps auth/session context', async () => {
    const client = new VayumiClient() as any;
    client.setServerUrl('http://localhost:8000');
    client.setAuthToken('bearer-1');
    client.sessionId = 'session-http';

    const fetchMock = vi.mocked(fetch);
    fetchMock.mockResolvedValue({
      ok: true,
      json: async () => ({
        text: 'http reply',
        spoken: false,
        response_id: 'resp-http',
      }),
    } as Response);

    const result = await client.sendChatMessage({
      text: 'fallback',
      attachments: [{ type: 'audio', url: 'https://example.com/audio.wav' }],
      respond_via: 'chat_only',
      interrupt_policy: 'queue',
    });

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, options] = fetchMock.mock.calls[0];
    expect(url).toBe('http://localhost:8000/chat');
    expect(options?.headers).toMatchObject({
      Authorization: 'Bearer bearer-1',
      'Content-Type': 'application/json',
    });
    expect(JSON.parse(String(options?.body))).toMatchObject({
      text: 'fallback',
      session_id: 'session-http',
      interrupt_policy: 'queue',
    });
    expect(result).toEqual({
      text: 'http reply',
      spoken: false,
      response_id: 'resp-http',
    });
  });

  it('returns to idle on interrupt acknowledgements', () => {
    const client = new VayumiClient() as any;
    client.setConnectionState('ai_speaking');

    client.processMessage({ type: 'interrupt_ack', trigger: 'manual' });

    expect(client.getConnectionState()).toBe('connected_idle');
  });
});
