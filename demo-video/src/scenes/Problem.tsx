import React from 'react';
import { useCurrentFrame, interpolate, spring, useVideoConfig } from 'remotion';
import { Background } from '../components/Background';
import { COLORS, FONTS } from '../styles/tokens';

export const Problem: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  // Left title: "Election Predictor" — spring at frame 20
  const leftTitleProgress = spring({
    frame: frame - 20,
    fps,
    config: { damping: 200, stiffness: 100, mass: 1 },
  });
  const leftTitleTranslateY = (1 - leftTitleProgress) * 30;

  // Left subtitle: "15-20pp systematic bias" — fade at frame 50
  const leftSubOpacity = interpolate(frame, [50, 70], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  const leftSubTranslateY = interpolate(frame, [50, 70], [15, 0], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });

  // Right title: "political_identity.py" — spring at frame 60
  const rightTitleProgress = spring({
    frame: frame - 60,
    fps,
    config: { damping: 200, stiffness: 100, mass: 1 },
  });
  const rightTitleTranslateY = (1 - rightTitleProgress) * 30;

  // Right subtitle: "516 lines - zero LLM calls" — fade at frame 90
  const rightSubOpacity = interpolate(frame, [90, 110], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  const rightSubTranslateY = interpolate(frame, [90, 110], [15, 0], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });

  // Bottom text — fade at frame 150
  const bottomOpacity = interpolate(frame, [150, 180], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  const bottomTranslateY = interpolate(frame, [150, 180], [20, 0], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });

  // Divider opacity
  const dividerOpacity = interpolate(frame, [10, 30], [0, 0.3], {
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

      {/* Split layout container */}
      <div
        style={{
          position: 'absolute',
          top: 0,
          left: 0,
          width: '100%',
          height: '100%',
          display: 'flex',
        }}
      >
        {/* Left half — the failure (red accent) */}
        <div
          style={{
            flex: 1,
            display: 'flex',
            flexDirection: 'column',
            justifyContent: 'center',
            alignItems: 'center',
            position: 'relative',
            padding: '0 80px',
          }}
        >
          {/* Red accent bar on left edge */}
          <div
            style={{
              position: 'absolute',
              left: 0,
              top: '25%',
              width: 3,
              height: '50%',
              backgroundColor: COLORS.accentRed,
              borderRadius: 2,
              boxShadow: `0 0 20px ${COLORS.accentRed}40`,
              opacity: leftTitleProgress,
            }}
          />

          {/* Left title */}
          <div
            style={{
              opacity: leftTitleProgress,
              transform: `translateY(${leftTitleTranslateY}px)`,
              fontSize: 40,
              fontFamily: FONTS.sans,
              fontWeight: 600,
              color: COLORS.textPrimary,
              letterSpacing: -0.5,
              textAlign: 'center',
            }}
          >
            Election Predictor
          </div>

          {/* Left subtitle */}
          <div
            style={{
              opacity: leftSubOpacity,
              transform: `translateY(${leftSubTranslateY}px)`,
              fontSize: 22,
              fontFamily: FONTS.sans,
              fontWeight: 400,
              color: COLORS.accentRed,
              marginTop: 16,
              textAlign: 'center',
            }}
          >
            15-20pp systematic bias
          </div>
        </div>

        {/* Center vertical divider */}
        <div
          style={{
            width: 1,
            backgroundColor: COLORS.textDim,
            opacity: dividerOpacity,
            alignSelf: 'stretch',
            margin: '120px 0',
          }}
        />

        {/* Right half — what existed (green accent) */}
        <div
          style={{
            flex: 1,
            display: 'flex',
            flexDirection: 'column',
            justifyContent: 'center',
            alignItems: 'center',
            position: 'relative',
            padding: '0 80px',
          }}
        >
          {/* Green accent bar on right edge */}
          <div
            style={{
              position: 'absolute',
              right: 0,
              top: '25%',
              width: 3,
              height: '50%',
              backgroundColor: COLORS.accent,
              borderRadius: 2,
              boxShadow: `0 0 20px ${COLORS.accent}40`,
              opacity: rightTitleProgress,
            }}
          />

          {/* Right title */}
          <div
            style={{
              opacity: rightTitleProgress,
              transform: `translateY(${rightTitleTranslateY}px)`,
              fontSize: 36,
              fontFamily: FONTS.mono,
              fontWeight: 500,
              color: COLORS.textPrimary,
              letterSpacing: -0.3,
              textAlign: 'center',
            }}
          >
            political_identity.py
          </div>

          {/* Right subtitle */}
          <div
            style={{
              opacity: rightSubOpacity,
              transform: `translateY(${rightSubTranslateY}px)`,
              fontSize: 22,
              fontFamily: FONTS.sans,
              fontWeight: 400,
              color: COLORS.accent,
              marginTop: 16,
              textAlign: 'center',
            }}
          >
            516 lines &middot; zero LLM calls
          </div>
        </div>
      </div>

      {/* Bottom center text */}
      <div
        style={{
          position: 'absolute',
          bottom: 120,
          left: 0,
          width: '100%',
          display: 'flex',
          justifyContent: 'center',
        }}
      >
        <div
          style={{
            opacity: bottomOpacity,
            transform: `translateY(${bottomTranslateY}px)`,
            fontSize: 36,
            fontFamily: FONTS.sans,
            fontWeight: 400,
            color: COLORS.textSecondary,
            letterSpacing: -0.3,
            textAlign: 'center',
          }}
        >
          The solution existed. Claude couldn't find it.
        </div>
      </div>
    </div>
  );
};
