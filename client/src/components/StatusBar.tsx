/**
 * Status bar component
 */
import React from 'react';
import { ConnectionState, Mode } from '../lib/types';

interface StatusBarProps {
  connectionState: ConnectionState;
  mode: Mode;
  isVADActive: boolean;
  isAISpeaking: boolean;
  lastSpeakerLabel: string | null;
  wakeWordVisible: boolean;
  wakeWordConfidence: number | null;
  wakeWordStatus: string;
  wakeWordLastHeard: string;
}

export const StatusBar: React.FC<StatusBarProps> = ({
  connectionState,
  mode,
  isVADActive,
  isAISpeaking,
  lastSpeakerLabel,
  wakeWordVisible,
  wakeWordConfidence,
  wakeWordStatus,
  wakeWordLastHeard,
}) => {
  const getStatusText = (): string => {
      if (wakeWordStatus === 'command-window-open') {
        return 'Listening for command...';
      }

      if (wakeWordStatus === 'sleeping') {
        return 'Sleeping...';
      }

      if (wakeWordStatus === 'waiting-for-vayumi') {
        return 'Say Vayumi to begin...';
      }

    switch (connectionState) {
      case 'disconnected':
        return 'Not connected';
      case 'connecting':
        return 'Connecting...';
      case 'connected_idle':
        return mode === 'meeting' ? 'Meeting recording...' : 'Listening for Vayumi...';
      case 'wake_detected':
        return 'I\'m listening...';
      case 'streaming_audio':
        return 'Hearing you...';
      case 'waiting_response':
        return 'Processing...';
      case 'ai_speaking':
        return 'Speaking...';
      default:
        return 'Unknown state';
    }
  };

  const getStatusColor = (): string => {
    switch (connectionState) {
      case 'disconnected':
        return '#999';
      case 'connected_idle':
        return '#4CAF50';
      case 'wake_detected':
      case 'streaming_audio':
        return '#2196F3';
      case 'ai_speaking':
        return '#9C27B0';
      default:
        return '#666';
    }
  };

  return (
    <div className="status-bar">
      <div className="status-content">
        <div
          className="status-indicator"
          style={{ backgroundColor: getStatusColor() }}
        />
        <span className="status-text">{getStatusText()}</span>
        {mode === 'meeting' && (
          <span className="status-badge">Meeting Mode</span>
        )}
      </div>
      {isAISpeaking && (
        <div className="ai-speaking-indicator">
          🔊 AI Speaking
        </div>
      )}
      {lastSpeakerLabel && (
        <div className="speaker-indicator">
          👤 {lastSpeakerLabel}
        </div>
      )}
      {wakeWordVisible && (
        <div className="wake-word-indicator">
          ✅ Wake word heard
          {wakeWordConfidence !== null && (
            <span className="wake-word-confidence">
              {` (${Math.round(wakeWordConfidence * 100)}%)`}
            </span>
          )}
        </div>
      )}
      <div className="wake-word-status-row">
        <span className="wake-word-status-label">Wake engine:</span>
        <span className={`wake-word-status-value status-${wakeWordStatus.replace(':', '-')}`}>
          {wakeWordStatus}
        </span>
      </div>
      {wakeWordLastHeard && (
        <div className="wake-word-last-heard">
          Last heard: "{wakeWordLastHeard}"
        </div>
      )}
    </div>
  );
};
