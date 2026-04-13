/**
 * Mode toggle component (Conversation / Meeting)
 */
import React from 'react';
import { Mode } from '../lib/types';

interface ModeToggleProps {
  currentMode: Mode;
  onModeChange: (mode: Mode) => Promise<void>;
  disabled?: boolean;
}

export const ModeToggle: React.FC<ModeToggleProps> = ({
  currentMode,
  onModeChange,
  disabled = false,
}) => {
  const [isLoading, setIsLoading] = React.useState(false);

  const handleModeChange = async (newMode: Mode) => {
    if (newMode === currentMode || isLoading || disabled) return;

    setIsLoading(true);
    try {
      await onModeChange(newMode);
    } catch (error) {
      console.error('Error changing mode:', error);
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="mode-toggle">
      <button
        className={`mode-btn ${currentMode === 'conversation' ? 'active' : ''}`}
        onClick={() => handleModeChange('conversation')}
        disabled={isLoading || disabled}
      >
        💬 Conversation
      </button>
      <button
        className={`mode-btn ${currentMode === 'meeting' ? 'active' : ''}`}
        onClick={() => handleModeChange('meeting')}
        disabled={isLoading || disabled}
      >
        📞 Meeting
      </button>
    </div>
  );
};
