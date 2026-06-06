import React from 'react';
import { useCurrentFrame, spring, useVideoConfig } from 'remotion';
import { COLORS, FONTS } from '../styles/tokens';

interface ScoreBarProps {
  label: string;
  value: number;
  maxValue?: number;
  delay?: number;
  color?: string;
  showPercent?: boolean;
}

export const ScoreBar: React.FC<ScoreBarProps> = ({
  label,
  value,
  maxValue = 1.0,
  delay = 0,
  color = COLORS.accent,
  showPercent = false,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const progress = spring({
    frame: frame - delay,
    fps,
    config: { damping: 200, stiffness: 100, mass: 1 },
  });

  const fraction = Math.min(value / maxValue, 1);
  const barWidth = fraction * progress * 100;

  const displayValue = showPercent
    ? `${Math.round(fraction * progress * 100)}%`
    : (value * progress).toFixed(2);

  return (
    <div style={{ marginBottom: 16 }}>
      {/* Label row */}
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          marginBottom: 6,
          fontFamily: FONTS.sans,
          fontSize: 14,
        }}
      >
        <span style={{ color: COLORS.textSecondary }}>{label}</span>
        <span style={{ color: COLORS.textPrimary, fontFamily: FONTS.mono }}>
          {displayValue}
        </span>
      </div>

      {/* Bar track */}
      <div
        style={{
          width: '100%',
          height: 8,
          borderRadius: 4,
          backgroundColor: 'rgba(255,255,255,0.08)',
          overflow: 'hidden',
        }}
      >
        {/* Filled bar */}
        <div
          style={{
            width: `${barWidth}%`,
            height: '100%',
            borderRadius: 4,
            backgroundColor: color,
            boxShadow: `0 0 12px ${color}40`,
          }}
        />
      </div>
    </div>
  );
};
