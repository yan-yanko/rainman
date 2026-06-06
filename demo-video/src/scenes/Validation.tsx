import React from 'react';
import { useCurrentFrame, interpolate, spring, useVideoConfig } from 'remotion';
import { Background } from '../components/Background';
import { GlassCard } from '../components/GlassCard';
import { COLORS, FONTS } from '../styles/tokens';

const CARDS = [
  { query: 'election voting bias', score: 0.937, delay: 40 },
  { query: 'political identity', score: 0.97, delay: 60 },
  { query: 'CEP calibration', score: 0.891, delay: 80 },
  { query: 'cognitrait memory', score: 0.867, delay: 100 },
];

export const Validation: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const titleOpacity = interpolate(frame, [10, 30], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });

  const subtitleOpacity = interpolate(frame, [200, 220], [0, 1], {
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
            fontSize: 36,
            fontWeight: 700,
            color: COLORS.textPrimary,
            opacity: titleOpacity,
            marginBottom: 48,
          }}
        >
          Validated on 307 Real Memories
        </div>

        {/* 2x2 Grid */}
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: '1fr 1fr',
            gap: 32,
            width: 880,
          }}
        >
          {CARDS.map((card) => {
            const cardSpring = spring({
              frame: frame - card.delay,
              fps,
              config: { damping: 20, stiffness: 200, mass: 1 },
            });

            const scale = interpolate(cardSpring, [0, 1], [0.8, 1], {
              extrapolateLeft: 'clamp',
              extrapolateRight: 'clamp',
            });

            const scoreProgress = interpolate(
              frame,
              [card.delay + 20, card.delay + 80],
              [0, card.score],
              { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' },
            );

            return (
              <div
                key={card.query}
                style={{
                  transform: `scale(${scale})`,
                }}
              >
                <GlassCard delay={card.delay} width={400}>
                  {/* Query */}
                  <div
                    style={{
                      fontFamily: FONTS.mono,
                      fontSize: 18,
                      color: COLORS.textSecondary,
                      marginBottom: 16,
                    }}
                  >
                    &quot;{card.query}&quot;
                  </div>

                  {/* Score */}
                  <div
                    style={{
                      fontFamily: FONTS.mono,
                      fontSize: 64,
                      fontWeight: 700,
                      color: COLORS.accent,
                      lineHeight: 1,
                    }}
                  >
                    {scoreProgress.toFixed(3)}
                  </div>
                </GlassCard>
              </div>
            );
          })}
        </div>

        {/* Subtitle */}
        <div
          style={{
            fontFamily: FONTS.sans,
            fontSize: 22,
            color: COLORS.textDim,
            opacity: subtitleOpacity,
            marginTop: 40,
          }}
        >
          Real project &middot; Real queries &middot; Real memories
        </div>
      </div>
    </div>
  );
};
