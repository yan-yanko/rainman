import { useVideoConfig } from 'remotion';
import { linearTiming, TransitionSeries } from '@remotion/transitions';
import { fade } from '@remotion/transitions/fade';
import { loadFont as loadInter } from '@remotion/google-fonts/Inter';
import { loadFont as loadJetBrains } from '@remotion/google-fonts/JetBrainsMono';

import { Hook } from './scenes/Hook';
import { Problem } from './scenes/Problem';
import { Insight } from './scenes/Insight';
import { Terminal } from './scenes/Terminal';
import { Scoring } from './scenes/Scoring';
import { Validation } from './scenes/Validation';
import { Setup } from './scenes/Setup';
import { CTA } from './scenes/CTA';

const { fontFamily: interFamily } = loadInter('normal', {
  weights: ['300', '400', '600', '700'],
  subsets: ['latin'],
});
const { fontFamily: jetbrainsFamily } = loadJetBrains('normal', {
  weights: ['400', '700'],
  subsets: ['latin'],
});

const TRANSITION_DURATION = 15; // frames

export const RainmanDemo: React.FC = () => {
  const { fps } = useVideoConfig();

  return (
    <div
      style={{
        fontFamily: interFamily,
        width: '100%',
        height: '100%',
      }}
    >
      <TransitionSeries>
        <TransitionSeries.Sequence durationInFrames={150}>
          <Hook />
        </TransitionSeries.Sequence>

        <TransitionSeries.Transition
          presentation={fade()}
          timing={linearTiming({ durationInFrames: TRANSITION_DURATION })}
        />

        <TransitionSeries.Sequence durationInFrames={360}>
          <Problem />
        </TransitionSeries.Sequence>

        <TransitionSeries.Transition
          presentation={fade()}
          timing={linearTiming({ durationInFrames: TRANSITION_DURATION })}
        />

        <TransitionSeries.Sequence durationInFrames={240}>
          <Insight />
        </TransitionSeries.Sequence>

        <TransitionSeries.Transition
          presentation={fade()}
          timing={linearTiming({ durationInFrames: TRANSITION_DURATION })}
        />

        <TransitionSeries.Sequence durationInFrames={600}>
          <Terminal />
        </TransitionSeries.Sequence>

        <TransitionSeries.Transition
          presentation={fade()}
          timing={linearTiming({ durationInFrames: TRANSITION_DURATION })}
        />

        <TransitionSeries.Sequence durationInFrames={360}>
          <Scoring />
        </TransitionSeries.Sequence>

        <TransitionSeries.Transition
          presentation={fade()}
          timing={linearTiming({ durationInFrames: TRANSITION_DURATION })}
        />

        <TransitionSeries.Sequence durationInFrames={300}>
          <Validation />
        </TransitionSeries.Sequence>

        <TransitionSeries.Transition
          presentation={fade()}
          timing={linearTiming({ durationInFrames: TRANSITION_DURATION })}
        />

        <TransitionSeries.Sequence durationInFrames={240}>
          <Setup />
        </TransitionSeries.Sequence>

        <TransitionSeries.Transition
          presentation={fade()}
          timing={linearTiming({ durationInFrames: TRANSITION_DURATION })}
        />

        <TransitionSeries.Sequence durationInFrames={150}>
          <CTA />
        </TransitionSeries.Sequence>
      </TransitionSeries>
    </div>
  );
};
