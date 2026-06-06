import React from 'react';
import { useCurrentFrame, spring, useVideoConfig, interpolate } from 'remotion';
import { COLORS } from '../styles/tokens';

interface GlassCardProps {
  children: React.ReactNode;
  delay?: number;
  width?: number;
  accentColor?: string;
}

export const GlassCard: React.FC<GlassCardProps> = ({
  children,
  delay = 0,
  width,
  accentColor = COLORS.accent,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const entrance = spring({
    frame: frame - delay,
    fps,
    config: { damping: 30, stiffness: 120, mass: 0.8 },
  });

  const opacity = interpolate(
    entrance,
    [0, 1],
    [0, 1],
    { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' },
  );

  const translateY = interpolate(
    entrance,
    [0, 1],
    [30, 0],
    { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' },
  );

  return (
    <div
      style={{
        opacity,
        transform: `translateY(${translateY}px)`,
        width: width ?? 'auto',
        backgroundColor: COLORS.bgCard,
        backdropFilter: 'blur(20px)',
        WebkitBackdropFilter: 'blur(20px)',
        border: `1px solid ${COLORS.bgCardBorder}`,
        borderRadius: 16,
        padding: 40,
        position: 'relative',
        overflow: 'hidden',
      }}
    >
      {/* Top edge glow */}
      <div
        style={{
          position: 'absolute',
          top: 0,
          left: '10%',
          width: '80%',
          height: 1,
          background: `linear-gradient(90deg, transparent, ${accentColor}60, transparent)`,
        }}
      />

      {/* Diffused glow behind top edge */}
      <div
        style={{
          position: 'absolute',
          top: -20,
          left: '20%',
          width: '60%',
          height: 40,
          background: `radial-gradient(ellipse, ${accentColor}15, transparent)`,
          filter: 'blur(10px)',
        }}
      />

      {children}
    </div>
  );
};
