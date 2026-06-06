import React from 'react';
import { COLORS, FONTS } from '../styles/tokens';

interface TerminalWindowProps {
  children: React.ReactNode;
  title?: string;
}

const DOT_COLORS = ['#ff5f56', '#ffbd2e', '#27c93f'];

export const TerminalWindow: React.FC<TerminalWindowProps> = ({
  children,
  title = '',
}) => {
  return (
    <div
      style={{
        backgroundColor: COLORS.terminalBg,
        border: `1px solid ${COLORS.terminalBorder}`,
        borderRadius: 12,
        overflow: 'hidden',
        fontFamily: FONTS.mono,
      }}
    >
      {/* Title bar */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          padding: '12px 16px',
          borderBottom: `1px solid ${COLORS.terminalBorder}`,
          position: 'relative',
        }}
      >
        {/* Traffic light dots */}
        <div style={{ display: 'flex', gap: 8 }}>
          {DOT_COLORS.map((color, i) => (
            <div
              key={i}
              style={{
                width: 12,
                height: 12,
                borderRadius: '50%',
                backgroundColor: color,
              }}
            />
          ))}
        </div>

        {/* Centered title */}
        {title && (
          <div
            style={{
              position: 'absolute',
              left: '50%',
              transform: 'translateX(-50%)',
              color: COLORS.textDim,
              fontSize: 13,
              fontFamily: FONTS.mono,
              letterSpacing: 0.5,
            }}
          >
            {title}
          </div>
        )}
      </div>

      {/* Body */}
      <div
        style={{
          padding: '20px 24px',
          color: COLORS.textPrimary,
          fontSize: 16,
          lineHeight: 1.6,
          fontFamily: FONTS.mono,
        }}
      >
        {children}
      </div>
    </div>
  );
};
