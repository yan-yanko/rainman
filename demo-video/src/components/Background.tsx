import React from 'react';
import { useCurrentFrame, interpolate, useVideoConfig } from 'remotion';
import { COLORS } from '../styles/tokens';

const ORBS = [
  { x: 300, y: 200, size: 420, color: COLORS.accent, driftX: 80, driftY: 60, period: 240 },
  { x: 1400, y: 700, size: 380, color: COLORS.accentWarm, driftX: -60, driftY: -80, period: 320 },
  { x: 900, y: 500, size: 440, color: COLORS.accentBlue, driftX: 70, driftY: -50, period: 280 },
];

export const Background: React.FC = () => {
  const frame = useCurrentFrame();
  const { width, height } = useVideoConfig();

  return (
    <div
      style={{
        position: 'absolute',
        top: 0,
        left: 0,
        width,
        height,
        backgroundColor: COLORS.bgDeep,
        overflow: 'hidden',
      }}
    >
      {/* Subtle grid overlay */}
      <div
        style={{
          position: 'absolute',
          top: 0,
          left: 0,
          width: '100%',
          height: '100%',
          backgroundImage: [
            `linear-gradient(rgba(255,255,255,0.03) 1px, transparent 1px)`,
            `linear-gradient(90deg, rgba(255,255,255,0.03) 1px, transparent 1px)`,
          ].join(', '),
          backgroundSize: '60px 60px',
        }}
      />

      {/* Floating ambient orbs */}
      {ORBS.map((orb, i) => {
        const cycleProgress = (frame % orb.period) / orb.period;

        const offsetX = interpolate(
          cycleProgress,
          [0, 0.25, 0.5, 0.75, 1],
          [0, orb.driftX, 0, -orb.driftX, 0],
          { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' },
        );

        const offsetY = interpolate(
          cycleProgress,
          [0, 0.25, 0.5, 0.75, 1],
          [0, orb.driftY, 0, -orb.driftY, 0],
          { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' },
        );

        const opacity = interpolate(
          cycleProgress,
          [0, 0.5, 1],
          [0.08, 0.12, 0.08],
          { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' },
        );

        return (
          <div
            key={i}
            style={{
              position: 'absolute',
              left: orb.x + offsetX - orb.size / 2,
              top: orb.y + offsetY - orb.size / 2,
              width: orb.size,
              height: orb.size,
              borderRadius: '50%',
              backgroundColor: orb.color,
              filter: 'blur(120px)',
              opacity,
            }}
          />
        );
      })}
    </div>
  );
};
