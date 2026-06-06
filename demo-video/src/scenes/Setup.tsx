import React from 'react';
import { useCurrentFrame, spring, interpolate, useVideoConfig } from 'remotion';
import { Background } from '../components/Background';
import { TerminalWindow } from '../components/TerminalWindow';
import { TypeWriter } from '../components/TypeWriter';
import { COLORS, FONTS } from '../styles/tokens';

const INSTALL_OUTPUT = [
  { text: 'Installing rainman-memory...', success: false },
  { text: '\u2713 Initialized .rainman/ in current directory', success: true },
  { text: '\u2713 Registered MCP server with Claude Code', success: true },
  { text: '\u2713 Configured 3 Claude Code hooks', success: true },
  { text: '\u2713 Created .mcp.json for project', success: true },
];

const CHECKS_COUNT = 14;

export const Setup: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

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
          alignItems: 'center',
          justifyContent: 'center',
          height: '100%',
          padding: '0 60px',
        }}
      >
        <div style={{ width: 1000 }}>
          <TerminalWindow title="terminal">
            {/* First command: pip install + setup */}
            <div style={{ marginBottom: 20 }}>
              <TypeWriter
                text="$ pip install rainman-memory && rainman setup"
                startFrame={10}
                speed={0.6}
              />
            </div>

            {/* Install output lines */}
            {INSTALL_OUTPUT.map((line, i) => {
              const lineDelay = 70 + i * 8;
              const lineSpring = spring({
                frame: frame - lineDelay,
                fps,
                config: { damping: 30, stiffness: 200, mass: 0.8 },
              });

              const opacity = interpolate(lineSpring, [0, 1], [0, 1], {
                extrapolateLeft: 'clamp',
                extrapolateRight: 'clamp',
              });

              const translateX = interpolate(lineSpring, [0, 1], [-20, 0], {
                extrapolateLeft: 'clamp',
                extrapolateRight: 'clamp',
              });

              return (
                <div
                  key={i}
                  style={{
                    opacity,
                    transform: `translateX(${translateX}px)`,
                    fontFamily: FONTS.mono,
                    fontSize: 16,
                    lineHeight: 1.8,
                    color: line.success ? COLORS.textDim : COLORS.textDim,
                  }}
                >
                  {line.success ? (
                    <>
                      <span style={{ color: COLORS.accent }}>{line.text.charAt(0)}</span>
                      <span>{line.text.slice(1)}</span>
                    </>
                  ) : (
                    line.text
                  )}
                </div>
              );
            })}

            {/* Blank line separator */}
            <div style={{ height: 24 }} />

            {/* Second command: rainman doctor */}
            {frame >= 130 && (
              <div style={{ marginBottom: 20 }}>
                <TypeWriter
                  text="$ rainman doctor"
                  startFrame={130}
                  speed={0.5}
                />
              </div>
            )}

            {/* Doctor output */}
            {frame >= 210 && (
              <div>
                {/* Result line */}
                {(() => {
                  const resultSpring = spring({
                    frame: frame - 210,
                    fps,
                    config: { damping: 30, stiffness: 200, mass: 0.8 },
                  });

                  const resultOpacity = interpolate(
                    resultSpring,
                    [0, 1],
                    [0, 1],
                    { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' },
                  );

                  return (
                    <div
                      style={{
                        opacity: resultOpacity,
                        fontFamily: FONTS.mono,
                        fontSize: 16,
                        color: COLORS.accent,
                        marginBottom: 12,
                      }}
                    >
                      14 checks passed, 0 failed
                    </div>
                  );
                })()}

                {/* Checkmark boxes */}
                <div style={{ display: 'flex', gap: 6 }}>
                  {Array.from({ length: CHECKS_COUNT }).map((_, i) => {
                    const checkDelay = 215 + i * 2;
                    const checkOpacity = interpolate(
                      frame,
                      [checkDelay, checkDelay + 5],
                      [0, 1],
                      {
                        extrapolateLeft: 'clamp',
                        extrapolateRight: 'clamp',
                      },
                    );

                    const checkScale = spring({
                      frame: frame - checkDelay,
                      fps,
                      config: { damping: 15, stiffness: 300, mass: 0.5 },
                    });

                    return (
                      <div
                        key={i}
                        style={{
                          opacity: checkOpacity,
                          transform: `scale(${checkScale})`,
                          width: 28,
                          height: 28,
                          borderRadius: 6,
                          backgroundColor: 'rgba(110,231,183,0.15)',
                          border: `1px solid ${COLORS.accent}`,
                          display: 'flex',
                          alignItems: 'center',
                          justifyContent: 'center',
                          fontFamily: FONTS.mono,
                          fontSize: 14,
                          color: COLORS.accent,
                        }}
                      >
                        {'\u2713'}
                      </div>
                    );
                  })}
                </div>
              </div>
            )}
          </TerminalWindow>
        </div>
      </div>
    </div>
  );
};
