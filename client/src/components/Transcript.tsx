/**
 * Live transcript display component
 */
import React, { useEffect, useRef } from 'react';

interface TranscriptProps {
  partialText: string;
  finalText: string[];
}

export const Transcript: React.FC<TranscriptProps> = ({ partialText, finalText }) => {
  const containerRef = useRef<HTMLDivElement>(null);

  // Auto-scroll to bottom
  useEffect(() => {
    if (containerRef.current) {
      containerRef.current.scrollTop = containerRef.current.scrollHeight;
    }
  }, [finalText, partialText]);

  return (
    <div className="transcript-container" ref={containerRef}>
      <div className="transcript-content">
        {/* Final transcript items */}
        {finalText.map((text, index) => (
          <div key={`final-${index}`} className="transcript-line final">
            {text}
          </div>
        ))}

        {/* Partial (live) text */}
        {partialText && <div className="transcript-line partial">{partialText}</div>}

        {!finalText.length && !partialText && (
          <div className="transcript-placeholder">Listening...</div>
        )}
      </div>
    </div>
  );
};
