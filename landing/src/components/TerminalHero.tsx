import { motion, useInView } from 'framer-motion';
import { useRef, useState, useEffect } from 'react';

const COMMAND = '$ rainman recall "election voting bias"';
const STATUS = 'Found 3 memories (scored by ACT-R retrieval)';

const RESULTS = [
  {
    rank: '#1',
    text: 'political_identity.py assigns party ID using ANES data',
    score: 0.937,
    category: 'pattern',
    categoryColor: '#6ee7b7',
  },
  {
    rank: '#2',
    text: 'election predictor has anti-incumbent voting bias',
    score: 0.891,
    category: 'failure',
    categoryColor: '#f87171',
  },
  {
    rank: '#3',
    text: 'CSS fix for dark mode sidebar',
    score: 0.234,
    category: 'solution',
    categoryColor: '#60a5fa',
  },
];

export function TerminalHero() {
  const ref = useRef<HTMLDivElement>(null);
  const isInView = useInView(ref, { once: true, margin: '-100px' });
  const [typedChars, setTypedChars] = useState(0);
  const [phase, setPhase] = useState(0); // 0=typing, 1=status, 2+=results

  useEffect(() => {
    if (!isInView) return;

    // Type the command
    if (typedChars < COMMAND.length) {
      const timer = setTimeout(
        () => setTypedChars((c) => c + 1),
        typedChars === 0 ? 600 : 35 + Math.random() * 25,
      );
      return () => clearTimeout(timer);
    }

    // After command typed, show phases
    if (phase === 0 && typedChars >= COMMAND.length) {
      const timer = setTimeout(() => setPhase(1), 400);
      return () => clearTimeout(timer);
    }
    if (phase >= 1 && phase <= RESULTS.length) {
      const timer = setTimeout(() => setPhase((p) => p + 1), 600);
      return () => clearTimeout(timer);
    }
  }, [isInView, typedChars, phase]);

  const displayedCommand = COMMAND.slice(0, typedChars);
  const showCursor = typedChars < COMMAND.length;

  return (
    <div ref={ref} className="w-full max-w-2xl lg:max-w-3xl mx-auto">
      <div className="liquid-glass rounded-xl overflow-hidden">
        {/* Title bar */}
        <div className="flex items-center gap-2 px-4 py-3 border-b border-white/[0.06]">
          <div className="w-3 h-3 rounded-full bg-[#ff5f56]" />
          <div className="w-3 h-3 rounded-full bg-[#ffbd2e]" />
          <div className="w-3 h-3 rounded-full bg-[#27c93f]" />
          <span className="flex-1 text-center text-xs text-white/30 font-mono">
            rainman
          </span>
        </div>

        {/* Terminal body */}
        <div className="p-5 md:p-6 font-mono text-sm md:text-base leading-relaxed min-h-[280px] md:min-h-[320px]">
          {/* Command line */}
          <div className="text-[#e8e8ed]">
            <span className="text-white/40">$</span>{' '}
            <span>{displayedCommand.slice(2)}</span>
            {showCursor && (
              <span className="cursor-blink text-accent">▋</span>
            )}
          </div>

          {/* Status line */}
          {phase >= 1 && (
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              transition={{ duration: 0.3 }}
              className="mt-4 text-white/30 text-xs md:text-sm"
            >
              {STATUS}
            </motion.div>
          )}

          {/* Results */}
          <div className="mt-3 space-y-4">
            {RESULTS.map((result, i) => {
              if (phase < i + 2) return null;
              return (
                <motion.div
                  key={i}
                  initial={{ opacity: 0, x: 20 }}
                  animate={{ opacity: 1, x: 0 }}
                  transition={{ duration: 0.4, ease: 'easeOut' }}
                >
                  <div className="flex items-baseline gap-2">
                    <span className="text-accent font-bold">
                      {result.rank}
                    </span>
                    <span className="text-[#e8e8ed] text-xs md:text-sm">
                      {result.text}
                    </span>
                  </div>
                  <div className="mt-1.5 flex items-center gap-3">
                    {/* Score bar */}
                    <div className="flex-1 max-w-[200px] h-1.5 bg-white/[0.06] rounded-full overflow-hidden">
                      <motion.div
                        className="h-full rounded-full"
                        style={{ backgroundColor: result.categoryColor }}
                        initial={{ width: 0 }}
                        animate={{ width: `${result.score * 100}%` }}
                        transition={{ duration: 0.8, delay: 0.2, ease: 'easeOut' }}
                      />
                    </div>
                    <span className="text-xs text-white/50 tabular-nums">
                      {result.score.toFixed(3)}
                    </span>
                    <span
                      className="text-[10px] uppercase tracking-wider"
                      style={{ color: result.categoryColor }}
                    >
                      {result.category}
                    </span>
                  </div>
                </motion.div>
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
}
