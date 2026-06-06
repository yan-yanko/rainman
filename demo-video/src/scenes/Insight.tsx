import React from 'react';
import { useCurrentFrame, interpolate, useVideoConfig } from 'remotion';
import { Background } from '../components/Background';
import { GlassCard } from '../components/GlassCard';
import { COLORS, FONTS } from '../styles/tokens';

export const Insight: React.FC = () => {
  const frame = useCurrentFrame();
  const { width } = useVideoConfig();

  // Arrow animation: drawn progressively at frame 90
  const arrowProgress = interpolate(frame, [90, 130], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });

  const arrowOpacity = interpolate(frame, [90, 100], [0, 0.6], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });

  const cardWidth = 500;
  const gap = 200;
  const totalWidth = cardWidth * 2 + gap;
  const startX = (width - totalWidth) / 2;

  // Arrow geometry
  const arrowStartX = startX + cardWidth + 30;
  const arrowEndX = startX + cardWidth + gap - 30;
  const arrowY = 0; // relative to SVG center
  const arrowLineEnd = arrowStartX + (arrowEndX - arrowStartX) * arrowProgress;
  const arrowHeadSize = 12;

  return (
    <div
      style={{
        position: 'relative',
        width: '100%',
        height: '100%',
      }}
    >
      <Background />

      {/* Cards container */}
      <div
        style={{
          position: 'absolute',
          top: 0,
          left: 0,
          width: '100%',
          height: '100%',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          gap,
        }}
      >
        {/* Left card: CLAUDE.md */}
        <GlassCard delay={20} width={cardWidth} accentColor={COLORS.textDim}>
          <div
            style={{
              fontSize: 28,
              fontFamily: FONTS.mono,
              fontWeight: 600,
              color: COLORS.textPrimary,
              marginBottom: 16,
            }}
          >
            CLAUDE.md
          </div>
          <div
            style={{
              fontSize: 18,
              fontFamily: FONTS.sans,
              fontWeight: 400,
              color: COLORS.textDim,
              lineHeight: 1.5,
            }}
          >
            Describes what things ARE
          </div>
        </GlassCard>

        {/* Right card: Rainman */}
        <GlassCard delay={50} width={cardWidth} accentColor={COLORS.accent}>
          <div
            style={{
              fontSize: 28,
              fontFamily: FONTS.sans,
              fontWeight: 600,
              color: COLORS.accent,
              marginBottom: 16,
            }}
          >
            Rainman
          </div>
          <div
            style={{
              fontSize: 18,
              fontFamily: FONTS.sans,
              fontWeight: 400,
              color: COLORS.accent,
              lineHeight: 1.5,
              opacity: 0.8,
            }}
          >
            Activates when you NEED them
          </div>
        </GlassCard>
      </div>

      {/* Animated arrow between cards */}
      <svg
        style={{
          position: 'absolute',
          top: 0,
          left: 0,
          width: '100%',
          height: '100%',
          pointerEvents: 'none',
        }}
      >
        {/* Arrow line */}
        {arrowProgress > 0 && (
          <g opacity={arrowOpacity}>
            <line
              x1={arrowStartX}
              y1={540}
              x2={arrowLineEnd}
              y2={540}
              stroke={COLORS.accent}
              strokeWidth={2}
              strokeLinecap="round"
            />
            {/* Arrowhead — only show when fully drawn */}
            {arrowProgress > 0.9 && (
              <polygon
                points={`
                  ${arrowEndX},${540}
                  ${arrowEndX - arrowHeadSize},${540 - arrowHeadSize / 2}
                  ${arrowEndX - arrowHeadSize},${540 + arrowHeadSize / 2}
                `}
                fill={COLORS.accent}
                opacity={interpolate(arrowProgress, [0.9, 1], [0, 1], {
                  extrapolateLeft: 'clamp',
                  extrapolateRight: 'clamp',
                })}
              />
            )}
          </g>
        )}
      </svg>
    </div>
  );
};
