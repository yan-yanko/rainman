import React from 'react';
import { useCurrentFrame, spring, interpolate, useVideoConfig } from 'remotion';
import { Background } from '../components/Background';
import { COLORS, FONTS } from '../styles/tokens';

export const CTA: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  // Wordmark entrance with heavy damping for a slow, weighty reveal
  const wordmarkSpring = spring({
    frame: frame - 10,
    fps,
    config: { damping: 200, stiffness: 100, mass: 1 },
  });

  const wordmarkOpacity = interpolate(wordmarkSpring, [0, 1], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });

  const wordmarkScale = interpolate(wordmarkSpring, [0, 1], [0.9, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });

  const taglineOpacity = interpolate(frame, [30, 50], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });

  const githubOpacity = interpolate(frame, [60, 80], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });

  const statsOpacity = interpolate(frame, [80, 100], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });

  return (
    <div
      style={{
        width: '100%',
        height: '100%',
        position: 'relative',
      }}
    >
      <Background />

      <div
        style={{
          position: 'relative',
          zIndex: 1,
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
          height: '100%',
        }}
      >
        {/* Wordmark */}
        <div
          style={{
            fontFamily: FONTS.sans,
            fontSize: 72,
            fontWeight: 700,
            color: COLORS.accent,
            opacity: wordmarkOpacity,
            transform: `scale(${wordmarkScale})`,
            textShadow: `0 0 40px ${COLORS.accentGlow}, 0 0 80px ${COLORS.accentGlow}, 0 0 120px rgba(110,231,183,0.08)`,
            marginBottom: 20,
          }}
        >
          Rainman
        </div>

        {/* Tagline */}
        <div
          style={{
            fontFamily: FONTS.sans,
            fontSize: 28,
            color: COLORS.textSecondary,
            opacity: taglineOpacity,
            marginBottom: 40,
          }}
        >
          Stop losing what you&apos;ve already built.
        </div>

        {/* GitHub URL */}
        <div
          style={{
            fontFamily: FONTS.mono,
            fontSize: 20,
            color: COLORS.textDim,
            opacity: githubOpacity,
            marginBottom: 16,
          }}
        >
          github.com/yan-yanko/rainman
        </div>

        {/* Stats */}
        <div
          style={{
            fontFamily: FONTS.sans,
            fontSize: 18,
            color: COLORS.textDim,
            opacity: statsOpacity,
          }}
        >
          124 tests &middot; 0 dependencies &middot; MIT
        </div>
      </div>
    </div>
  );
};
