import React from 'react';
import { useCurrentFrame, interpolate } from 'remotion';
import { Background } from '../components/Background';
import { COLORS, FONTS } from '../styles/tokens';

export const Hook: React.FC = () => {
  const frame = useCurrentFrame();

  // First line: "The AI forgot the fix."
  const line1Opacity = interpolate(frame, [15, 35], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  const line1TranslateY = interpolate(frame, [15, 35], [20, 0], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });

  // Second line: "The fix it built."
  const line2Opacity = interpolate(frame, [75, 95], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  const line2TranslateY = interpolate(frame, [75, 95], [20, 0], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });

  return (
    <div
      style={{
        position: 'relative',
        width: '100%',
        height: '100%',
      }}
    >
      <Background />

      {/* Centered text container */}
      <div
        style={{
          position: 'absolute',
          top: 0,
          left: 0,
          width: '100%',
          height: '100%',
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
          gap: 24,
        }}
      >
        {/* First line */}
        <div
          style={{
            opacity: line1Opacity,
            transform: `translateY(${line1TranslateY}px)`,
            fontSize: 56,
            fontFamily: FONTS.sans,
            fontWeight: 300,
            color: COLORS.textPrimary,
            letterSpacing: -0.5,
          }}
        >
          The AI forgot the fix.
        </div>

        {/* Second line */}
        <div
          style={{
            opacity: line2Opacity,
            transform: `translateY(${line2TranslateY}px)`,
            fontSize: 56,
            fontFamily: FONTS.sans,
            fontWeight: 300,
            color: COLORS.textSecondary,
            letterSpacing: -0.5,
          }}
        >
          The fix it built.
        </div>
      </div>
    </div>
  );
};
