/**
 * Connection toggle component
 */
import React, { useState, useEffect } from 'react';

interface ConnectToggleProps {
  connected: boolean;
  connecting: boolean;
  onConnect: () => Promise<void>;
  onDisconnect: () => void;
}

export const ConnectToggle: React.FC<ConnectToggleProps> = ({
  connected,
  connecting,
  onConnect,
  onDisconnect,
}) => {
  const [isLoading, setIsLoading] = useState(false);

  const handleToggle = async () => {
    setIsLoading(true);
    try {
      if (connected) {
        onDisconnect();
      } else {
        await onConnect();
      }
    } catch (error) {
      console.error('Connection toggle error:', error);
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="connect-toggle">
      <button
        onClick={handleToggle}
        disabled={isLoading || connecting}
        className={`connect-btn ${connected ? 'connected' : 'disconnected'}`}
      >
        {isLoading || connecting ? (
          <span>Connecting...</span>
        ) : connected ? (
          <span>Disconnect</span>
        ) : (
          <span>Connect</span>
        )}
      </button>
      <div className={`status-indicator ${connected ? 'active' : 'inactive'}`} />
    </div>
  );
};
