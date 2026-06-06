import React from 'react';
import { useCurrentFrame } from 'remotion';
import { COLORS, FONTS } from '../styles/tokens';

interface TypeWriterProps {
  text: string;
  startFrame?: number;
  speed?: number;
  cursorChar?: string;
  style?: React.CSSProperties;
}

export const TypeWriter: React.FC<TypeWriterProps> = ({
  text,
  startFrame = 0,
  speed = 0.5,
  cursorChar = '\u2588',
  style,
}) => {
  const frame = useCurrentFrame();
  const elapsed = Math.max(0, frame - startFrame);

  const charCount = Math.min(Math.floor(elapsed * speed), text.length);
  const visibleText = text.slice(0, charCount);

  const cursorVisible = Math.floor(frame / 15) % 2 === 0;
  const isComplete = charCount >= text.length;

  return (
    <span
      style={{
        fontFamily: FONTS.mono,
        color: COLORS.textPrimary,
        whiteSpace: 'pre-wrap',
        ...style,
      }}
    >
      {visibleText}
      {(!isComplete || cursorVisible) && (
        <span style={{ color: COLORS.accent }}>{cursorChar}</span>
      )}
    </span>
  );
};
