/**
 * Chat panel component
 */
import React, { useState, useRef, useEffect } from 'react';
import { ChatMessage, ChatResponse } from '../lib/types';

interface ChatPanelProps {
  messages: Array<{
    role: 'user' | 'ai' | 'system';
    text: string;
    timestamp: Date;
  }>;
  onSendMessage: (message: ChatMessage) => Promise<ChatResponse | null>;
  disabled?: boolean;
}

export const ChatPanel: React.FC<ChatPanelProps> = ({ messages, onSendMessage, disabled = false }) => {
  const [inputText, setInputText] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  // Auto-scroll to bottom
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const handleSendMessage = async () => {
    if (!inputText.trim()) return;

    setIsLoading(true);
    try {
      await onSendMessage({
        text: inputText,
        respond_via: 'chat_only',
        interrupt_policy: 'queue',
      });
      setInputText('');
    } catch (error) {
      console.error('Error sending message:', error);
    } finally {
      setIsLoading(false);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSendMessage();
    }
  };

  return (
    <div className="chat-panel">
      <div className="chat-messages">
        {messages.length === 0 ? (
          <div className="chat-placeholder">Start a conversation...</div>
        ) : (
          messages.map((msg, index) => (
            <div key={index} className={`chat-message ${msg.role}`}>
              <div className="message-content">{msg.text}</div>
              <div className="message-time">
                {msg.timestamp.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
              </div>
            </div>
          ))
        )}
        <div ref={messagesEndRef} />
      </div>

      <div className="chat-input-area">
        <div className="input-wrapper">
          <textarea
            value={inputText}
            onChange={(e) => setInputText(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Type a message or ask a question..."
            disabled={disabled || isLoading}
            rows={2}
          />
          <button
            onClick={handleSendMessage}
            disabled={disabled || isLoading || !inputText.trim()}
            className="send-btn"
          >
            Send
          </button>
        </div>
      </div>
    </div>
  );
};
