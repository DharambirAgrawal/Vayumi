/**
 * Animated orb/visualizer component
 */
import React, { useEffect, useRef } from 'react';
import { ConnectionState } from '../lib/types';

interface OrbProps {
  state: ConnectionState;
}

export const Orb: React.FC<OrbProps> = ({ state }) => {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const animationRef = useRef<number | null>(null);
  const timeRef = useRef(0);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const animate = () => {
      timeRef.current += 0.016; // ~60fps

      // Clear canvas
      ctx.fillStyle = 'rgba(0, 0, 0, 0.1)';
      ctx.fillRect(0, 0, canvas.width, canvas.height);

      const centerX = canvas.width / 2;
      const centerY = canvas.height / 2;
      const baseRadius = 40;

      // Draw orb based on state
      let radius = baseRadius;
      let color = '#999';
      let pulse = 0;

      switch (state) {
        case 'disconnected':
          color = '#999';
          radius = baseRadius;
          break;
        case 'connected_idle':
          color = '#4CAF50';
          pulse = Math.sin(timeRef.current * 2) * 5;
          break;
        case 'wake_detected':
          color = '#FF9800';
          radius = baseRadius + 20;
          pulse = Math.sin(timeRef.current * 4) * 8;
          break;
        case 'streaming_audio':
          color = '#2196F3';
          const waveAmplitude = 15;
          const wave = Math.sin(timeRef.current * 8) * waveAmplitude;
          radius = baseRadius + wave;
          break;
        case 'ai_speaking':
          color = '#9C27B0';
          pulse = Math.sin(timeRef.current * 3) * 10;
          break;
        default:
          color = '#666';
      }

      // Draw main orb
      ctx.fillStyle = color;
      ctx.beginPath();
      ctx.arc(centerX, centerY, radius + pulse, 0, Math.PI * 2);
      ctx.fill();

      // Draw glow effect
      ctx.strokeStyle = color;
      ctx.globalAlpha = 0.3;
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.arc(centerX, centerY, radius + pulse + 10, 0, Math.PI * 2);
      ctx.stroke();
      ctx.globalAlpha = 1;

      animationRef.current = requestAnimationFrame(animate);
    };

    // Resize canvas
    canvas.width = 120;
    canvas.height = 120;

    animate();

    return () => {
      if (animationRef.current) {
        cancelAnimationFrame(animationRef.current);
      }
    };
  }, [state]);

  return (
    <div className="orb-container">
      <canvas ref={canvasRef} className="orb-canvas" />
    </div>
  );
};
