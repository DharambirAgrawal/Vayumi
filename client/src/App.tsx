import React, { useState, useEffect, useCallback } from 'react';
import './App.css';
import VayumiClient from './lib/VayumiClient';
import { ConnectionState, Mode, ChatMessage, ChatResponse, AuthUser } from './lib/types';
import { ConnectToggle } from './components/ConnectToggle';
import { Orb } from './components/Orb';
import { Transcript } from './components/Transcript';
import { ChatPanel } from './components/ChatPanel';
import { ModeToggle } from './components/ModeToggle';
import { StatusBar } from './components/StatusBar';

function App() {
  const serverUrl = import.meta.env.VITE_SERVER_URL || 'http://localhost:8000';
  const [client] = useState(() => new VayumiClient());
  const [connectionState, setConnectionState] = useState<ConnectionState>('disconnected');
  const [mode, setMode] = useState<Mode>('conversation');
  const [partialTranscript, setPartialTranscript] = useState('');
  const [finalTranscripts, setFinalTranscripts] = useState<string[]>([]);
  const [chatMessages, setChatMessages] = useState<Array<{ role: 'user' | 'ai' | 'system'; text: string; timestamp: Date }>>([]);
  const [isVADActive, setIsVADActive] = useState(false);
  const [isAISpeaking, setIsAISpeaking] = useState(false);
  const [lastSpeakerLabel, setLastSpeakerLabel] = useState<string | null>(null);
  const [wakeWordVisible, setWakeWordVisible] = useState(false);
  const [wakeWordConfidence, setWakeWordConfidence] = useState<number | null>(null);
  const [wakeWordStatus, setWakeWordStatus] = useState('idle');
  const [wakeWordLastHeard, setWakeWordLastHeard] = useState('');
  const [authMode, setAuthMode] = useState<'login' | 'register'>('login');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [name, setName] = useState('');
  const [authUser, setAuthUser] = useState<AuthUser | null>(null);
  const [authError, setAuthError] = useState<string | null>(null);
  const [authLoading, setAuthLoading] = useState(false);

  useEffect(() => {
    const token = window.localStorage.getItem('vayumi_access_token');
    client.setAuthToken(token);
    client.setServerUrl(serverUrl);

    if (!token) {
      return;
    }

    setAuthLoading(true);
    client
      .connect(serverUrl)
      .then(() => client.me())
      .then((user) => {
        setAuthUser(user);
      })
      .catch((error) => {
        console.error('Auto-auth failed:', error);
        client.setAuthToken(null);
        window.localStorage.removeItem('vayumi_access_token');
      })
      .finally(() => {
        setAuthLoading(false);
      });
  }, [client]);

  // Subscribe to client events on mount
  useEffect(() => {
    const unsubscribers: Array<() => void> = [];

    // Connection state changes
    const offState = client.onStateChange?.((state: ConnectionState) => {
      setConnectionState(state);
    });
    if (offState) {
      unsubscribers.push(offState);
    }

    // Transcript events
    const offPartial = client.on?.('transcription_partial', (text: string) => {
      setPartialTranscript(text);
    });
    if (offPartial) {
      unsubscribers.push(offPartial);
    }

    const offFinal = client.on?.('transcription_final', (payload: string | { text?: string; confidence?: number; speaker_label?: string }) => {
      const isObjectPayload = typeof payload !== 'string';
      const finalText = typeof payload === 'string' ? payload : (payload?.text || '');
      if (!finalText) {
        return;
      }

      const speakerLabel = isObjectPayload ? (payload as { speaker_label?: string }).speaker_label ?? null : null;
      const displayText = speakerLabel ? `[${speakerLabel}] ${finalText}` : finalText;

      setLastSpeakerLabel(speakerLabel);
      setFinalTranscripts((prev) => [...prev, displayText]);
      setPartialTranscript('');
      // Auto-add to chat on final transcription
      setChatMessages((prev) => [...prev, { role: 'user', text: displayText, timestamp: new Date() }]);
    });
    if (offFinal) {
      unsubscribers.push(offFinal);
    }

    // VAD events
    const offVADStart = client.on?.('vad_speech_start', () => {
      setIsVADActive(true);
    });
    if (offVADStart) {
      unsubscribers.push(offVADStart);
    }

    const offVADEnd = client.on?.('vad_speech_end', () => {
      setIsVADActive(false);
    });
    if (offVADEnd) {
      unsubscribers.push(offVADEnd);
    }

    // Agent events
    const offAgentSpeaking = client.on?.('agent_speaking', () => {
      setIsAISpeaking(true);
    });
    if (offAgentSpeaking) {
      unsubscribers.push(offAgentSpeaking);
    }

    const offAgentDone = client.on?.('agent_done', () => {
      setIsAISpeaking(false);
    });
    if (offAgentDone) {
      unsubscribers.push(offAgentDone);
    }

    // Mode changes
    const offMode = client.on?.('mode_changed', (payload: Mode | { mode?: Mode }) => {
      const newMode = typeof payload === 'string' ? payload : payload?.mode;
      if (newMode === 'conversation' || newMode === 'meeting') {
        setMode(newMode);
      }
    });
    if (offMode) {
      unsubscribers.push(offMode);
    }

    const offSpeaker = client.on?.('speaker_identified', (speaker: { speaker_label?: string }) => {
      setLastSpeakerLabel(speaker?.speaker_label ?? null);
    });
    if (offSpeaker) {
      unsubscribers.push(offSpeaker);
    }

    // Wake word events
    const offWakeWord = client.on?.('wake_word_detected', (confidence: number) => {
      setWakeWordConfidence(confidence);
      setWakeWordVisible(true);

      // Keep indicator visible briefly so it is easy to notice.
      window.setTimeout(() => {
        setWakeWordVisible(false);
      }, 1800);
    });

    const offWakeWordStatus = client.on?.('wake_word_status', (status: string) => {
      setWakeWordStatus(status);
    });

    const offWakeWordDebug = client.on?.('wake_word_debug', (text: string) => {
      setWakeWordLastHeard(text);
    });

    // Chat response events
    const offChat = client.onChatResponse?.((response: any) => {
      setChatMessages((prev) => [...prev, { role: 'ai', text: response.text, timestamp: new Date() }]);
    });
    if (offChat) {
      unsubscribers.push(offChat);
    }

    return () => {
      unsubscribers.forEach((unsubscribe) => unsubscribe());
      if (offWakeWord) {
        offWakeWord();
      }
      if (offWakeWordStatus) {
        offWakeWordStatus();
      }
      if (offWakeWordDebug) {
        offWakeWordDebug();
      }
    };
  }, [client]);

  const handleConnect = useCallback(async () => {
    try {
      client.setServerUrl(serverUrl);
      await client.connect(serverUrl);
    } catch (error) {
      console.error('Connection failed:', error);
    }
  }, [client]);

  const handleDisconnect = useCallback(() => {
    client.disconnect?.();
  }, [client]);

  const handleAuthSubmit = useCallback(async () => {
    try {
      setAuthError(null);
      setAuthLoading(true);
      client.setServerUrl(serverUrl);

      const authResponse = authMode === 'register'
        ? await client.register(email, password, name || undefined)
        : await client.login(email, password);

      window.localStorage.setItem('vayumi_access_token', authResponse.access_token);
      client.setAuthToken(authResponse.access_token);
      setAuthUser(authResponse.user);
      await client.connect(serverUrl);
    } catch (error) {
      setAuthError(String(error));
    } finally {
      setAuthLoading(false);
    }
  }, [authMode, client, email, name, password]);

  const handleLogout = useCallback(() => {
    client.disconnect?.('logout');
    client.setAuthToken(null);
    window.localStorage.removeItem('vayumi_access_token');
    setAuthUser(null);
    setEmail('');
    setPassword('');
    setName('');
  }, [client]);

  const handleModeChange = useCallback(
    async (newMode: Mode) => {
      try {
        await client.switchMode?.(newMode);
      } catch (error) {
        console.error('Mode change failed:', error);
      }
    },
    [client]
  );

  const handleSendMessage = useCallback(
    async (message: ChatMessage): Promise<ChatResponse | null> => {
      const userMessage = {
        role: 'user' as const,
        text: message.text || '',
        timestamp: new Date(),
      };

      setChatMessages((prev) => [...prev, userMessage]);

      try {
        const response = await client.sendChatMessage?.(message);
        if (response) {
          setChatMessages((prev) => [...prev, { role: 'ai', text: response.text, timestamp: new Date() }]);
        }
        return response || null;
      } catch (error) {
        console.error('Send message failed:', error);
        setChatMessages((prev) => [
          ...prev,
          {
            role: 'system',
            text: 'Message could not be delivered to the assistant.',
            timestamp: new Date(),
          },
        ]);
        return null;
      }
    },
    [client]
  );

  const handlePushToTalkStart = useCallback(async () => {
    try {
      await client.triggerManualPushToTalk?.();
    } catch (error) {
      console.error('Push-to-talk start failed:', error);
    }
  }, [client]);

  const handlePushToTalkEnd = useCallback(async () => {
    try {
      await client.releaseManualPushToTalk?.();
    } catch (error) {
      console.error('Push-to-talk end failed:', error);
    }
  }, [client]);

  const isConnected = connectionState !== 'disconnected' && connectionState !== 'connecting';
  const isConnecting = connectionState === 'connecting';

  if (!authUser) {
    return (
      <div className="App">
        <div className="vayumi-container" style={{ maxWidth: 560, height: 'auto' }}>
          <header className="vayumi-header">
            <h1>🎤 Vayumi</h1>
            <span className="subtitle">Sign in to continue</span>
          </header>
          <div className="left-panel" style={{ borderRight: 'none' }}>
            <div className="chat-section">
              <h3>{authMode === 'register' ? 'Create Account' : 'Login'}</h3>
              <input value={email} onChange={(e) => setEmail(e.target.value)} placeholder="Email" />
              <input value={password} onChange={(e) => setPassword(e.target.value)} placeholder="Password" type="password" />
              {authMode === 'register' && (
                <input value={name} onChange={(e) => setName(e.target.value)} placeholder="Name (optional)" />
              )}
              <button className="send-btn" onClick={handleAuthSubmit} disabled={authLoading || !email || !password}>
                {authLoading ? 'Please wait...' : authMode === 'register' ? 'Register' : 'Login'}
              </button>
              <button
                className="ptt-btn"
                onClick={() => setAuthMode((m) => (m === 'login' ? 'register' : 'login'))}
                disabled={authLoading}
              >
                {authMode === 'login' ? 'Need an account? Register' : 'Already have an account? Login'}
              </button>
              {authError && <div className="wake-word-last-heard">{authError}</div>}
            </div>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="App">
      <div className="vayumi-container">
        <header className="vayumi-header">
          <h1>🎤 Vayumi</h1>
          <span className="subtitle">AI Agent Voice Platform · {authUser.email}</span>
          <button className="ptt-btn" style={{ maxWidth: 180 }} onClick={handleLogout}>Logout</button>
        </header>

        <div className="vayumi-body">
          {/* Left panel */}
          <div className="left-panel">
            <div className="orb-section">
              <Orb state={connectionState} />
            </div>

            <div className="controls-section">
              <ConnectToggle
                connected={isConnected}
                connecting={isConnecting}
                onConnect={handleConnect}
                onDisconnect={handleDisconnect}
              />
            </div>

            <div className="ptt-section">
              <button
                className="ptt-btn"
                disabled={!isConnected}
                onMouseDown={handlePushToTalkStart}
                onMouseUp={handlePushToTalkEnd}
                onMouseLeave={handlePushToTalkEnd}
                onTouchStart={handlePushToTalkStart}
                onTouchEnd={handlePushToTalkEnd}
                title="Hold to talk"
              >
                Hold To Talk (Manual Wake)
              </button>
            </div>

            <div className="status-section">
              <StatusBar
                connectionState={connectionState}
                mode={mode}
                isVADActive={isVADActive}
                isAISpeaking={isAISpeaking}
                lastSpeakerLabel={lastSpeakerLabel}
                wakeWordVisible={wakeWordVisible}
                wakeWordConfidence={wakeWordConfidence}
                wakeWordStatus={wakeWordStatus}
                wakeWordLastHeard={wakeWordLastHeard}
              />
            </div>

            <div className="mode-section">
              <ModeToggle
                currentMode={mode}
                onModeChange={handleModeChange}
                disabled={!isConnected}
              />
            </div>

            <div className="transcript-section">
              <h3>Live Transcript</h3>
              <Transcript partialText={partialTranscript} finalText={finalTranscripts} />
            </div>
          </div>

          {/* Right panel */}
          <div className="right-panel">
            <div className="chat-section">
              <h3>Chatbot</h3>
              <ChatPanel messages={chatMessages} onSendMessage={handleSendMessage} disabled={isConnecting} />
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

export default App;
