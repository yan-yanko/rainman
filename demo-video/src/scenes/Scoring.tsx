import React from 'react';
import { useCurrentFrame, interpolate } from 'remotion';
import { Background } from '../components/Background';
import { ScoreBar } from '../components/ScoreBar';
import { COLORS, FONTS } from '../styles/tokens';

const SIGNALS = [
  {
    label: 'Keyword Match',
    value: 35,
    delay: 60,
    color: COLORS.accent,
    description: 'TF-IDF weighted term overlap',
  },
  {
    label: 'Recency Decay',
    value: 25,
    delay: 100,
    color: COLORS.accentBlue,
    description: 'Power-law decay (t + 1)^(-0.5)',
  },
  {
    label: 'Importance',
    value: 20,
    delay: 140,
    color: COLORS.accentWarm,
    description: 'Access count + emotional salience',
  },
  {
    label: 'Associative Links',
    value: 20,
    delay: 180,
    color: COLORS.accentRed,
    description: 'File refs \u00b7 tags \u00b7 co-occurrence',
  },
];

export const Scoring: React.FC = () => {
  const frame = useCurrentFrame();

  const titleOpacity = interpolate(frame, [10, 30], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });

  const subtitleOpacity = interpolate(frame, [30, 50], [0, 1], {
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
          padding: '0 60px',
        }}
      >
        {/* Title */}
        <div
          style={{
            fontFamily: FONTS.sans,
            fontSize: 42,
            fontWeight: 700,
            color: COLORS.textPrimary,
            opacity: titleOpacity,
            marginBottom: 12,
          }}
        >
          Four Scoring Signals
        </div>

        {/* Subtitle */}
        <div
          style={{
            fontFamily: FONTS.sans,
            fontSize: 22,
            color: COLORS.textDim,
            opacity: subtitleOpacity,
            marginBottom: 60,
          }}
        >
          ACT-R cognitive architecture &middot; Two-phase retrieval
        </div>

        {/* Score bars */}
        <div style={{ width: 800 }}>
          {SIGNALS.map((signal) => {
            const descOpacity = interpolate(
              frame,
              [signal.delay + 30, signal.delay + 50],
              [0, 1],
              { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' },
            );

            return (
              <div key={signal.label} style={{ marginBottom: 32 }}>
                <div
                  style={{
                    display: 'flex',
                    alignItems: 'flex-start',
                    gap: 24,
                  }}
                >
                  {/* Label column */}
                  <div
                    style={{
                      width: 200,
                      flexShrink: 0,
                      fontFamily: FONTS.sans,
                      fontSize: 18,
                      fontWeight: 600,
                      color: COLORS.textSecondary,
                      paddingTop: 2,
                    }}
                  >
                    {signal.label}
                  </div>

                  {/* Bar column */}
                  <div style={{ flex: 1 }}>
                    <ScoreBar
                      label=""
                      value={signal.value}
                      maxValue={100}
                      delay={signal.delay}
                      color={signal.color}
                      showPercent
                    />
                  </div>
                </div>

                {/* Description */}
                <div
                  style={{
                    marginLeft: 224,
                    fontFamily: FONTS.mono,
                    fontSize: 16,
                    color: COLORS.textDim,
                    opacity: descOpacity,
                    marginTop: -8,
                  }}
                >
                  {signal.description}
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
};
