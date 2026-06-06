import React from 'react';
import { useCurrentFrame, interpolate, spring, useVideoConfig } from 'remotion';
import { Background } from '../components/Background';
import { TerminalWindow } from '../components/TerminalWindow';
import { TypeWriter } from '../components/TypeWriter';
import { ScoreBar } from '../components/ScoreBar';
import { COLORS, FONTS } from '../styles/tokens';

interface ResultEntryProps {
  frame: number;
  fps: number;
  appearFrame: number;
  rank: string;
  description: string;
  scoreLabel: string;
  scoreValue: number;
  scoreDelay: number;
  scoreColor?: string;
  categoryLabel: string;
  categoryColor: string;
}

const ResultEntry: React.FC<ResultEntryProps> = ({
  frame,
  fps,
  appearFrame,
  rank,
  description,
  scoreLabel,
  scoreValue,
  scoreDelay,
  scoreColor = COLORS.accent,
  categoryLabel,
  categoryColor,
}) => {
  const entryProgress = spring({
    frame: frame - appearFrame,
    fps,
    config: { damping: 200, stiffness: 100, mass: 1 },
  });

  const translateX = (1 - entryProgress) * 40;

  return (
    <div
      style={{
        opacity: entryProgress,
        transform: `translateX(${translateX}px)`,
        marginBottom: 8,
      }}
    >
      {/* Result line */}
      <div
        style={{
          display: 'flex',
          alignItems: 'baseline',
          gap: 12,
          fontFamily: FONTS.mono,
          fontSize: 16,
          lineHeight: 1.8,
        }}
      >
        <span style={{ color: COLORS.accent, fontWeight: 600 }}>{rank}</span>
        <span style={{ color: COLORS.textPrimary }}>{description}</span>
      </div>

      {/* Score bar + category tag row */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 20,
          paddingLeft: 36,
          marginTop: 2,
        }}
      >
        <div style={{ flex: 1, maxWidth: 300 }}>
          <ScoreBar
            label={scoreLabel}
            value={scoreValue}
            delay={scoreDelay}
            color={scoreColor}
          />
        </div>
        <span
          style={{
            fontFamily: FONTS.mono,
            fontSize: 11,
            color: categoryColor,
            textTransform: 'uppercase',
            letterSpacing: 1.5,
            opacity: entryProgress,
          }}
        >
          {categoryLabel}
        </span>
      </div>
    </div>
  );
};

export const Terminal: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  // "Found 3 memories..." text — fade at frame 120
  const foundTextOpacity = interpolate(frame, [120, 140], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });

  // Blank line visibility gates
  const showBlankLine1 = frame >= 100;
  const showFoundText = frame >= 120;
  const showBlankLine2 = frame >= 150;

  return (
    <div
      style={{
        position: 'relative',
        width: '100%',
        height: '100%',
      }}
    >
      <Background />

      {/* Terminal container — centered */}
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
        }}
      >
        <div style={{ width: 1200 }}>
          <TerminalWindow title="rainman">
            {/* Command line */}
            <div style={{ marginBottom: 8 }}>
              <TypeWriter
                text='$ rainman recall "election voting bias"'
                startFrame={15}
                speed={0.4}
              />
            </div>

            {/* Blank line after command */}
            {showBlankLine1 && (
              <div style={{ height: 24 }} />
            )}

            {/* Found text */}
            {showFoundText && (
              <div
                style={{
                  opacity: foundTextOpacity,
                  fontFamily: FONTS.mono,
                  fontSize: 14,
                  color: COLORS.textDim,
                  marginBottom: 4,
                }}
              >
                Found 3 memories (scored by ACT-R retrieval)
              </div>
            )}

            {/* Blank line before results */}
            {showBlankLine2 && (
              <div style={{ height: 16 }} />
            )}

            {/* Result #1 */}
            {frame >= 170 && (
              <ResultEntry
                frame={frame}
                fps={fps}
                appearFrame={170}
                rank="#1"
                description="political_identity.py assigns party ID using ANES data"
                scoreLabel="relevance"
                scoreValue={0.937}
                scoreDelay={190}
                scoreColor={COLORS.accent}
                categoryLabel="pattern"
                categoryColor={COLORS.textSecondary}
              />
            )}

            {/* Result #2 */}
            {frame >= 250 && (
              <ResultEntry
                frame={frame}
                fps={fps}
                appearFrame={250}
                rank="#2"
                description="election predictor has anti-incumbent voting bias"
                scoreLabel="relevance"
                scoreValue={0.891}
                scoreDelay={270}
                scoreColor={COLORS.accent}
                categoryLabel="failure"
                categoryColor={COLORS.accentRed}
              />
            )}

            {/* Result #3 */}
            {frame >= 330 && (
              <ResultEntry
                frame={frame}
                fps={fps}
                appearFrame={330}
                rank="#3"
                description="CSS fix for dark mode sidebar"
                scoreLabel="relevance"
                scoreValue={0.234}
                scoreDelay={350}
                scoreColor={COLORS.accent}
                categoryLabel="solution"
                categoryColor={COLORS.accentBlue}
              />
            )}
          </TerminalWindow>
        </div>
      </div>
    </div>
  );
};
