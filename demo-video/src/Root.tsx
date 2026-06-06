import { Composition } from 'remotion';
import { RainmanDemo } from './RainmanDemo';
import { VIDEO } from './styles/tokens';

export const RemotionRoot: React.FC = () => {
  return (
    <Composition
      id="RainmanDemo"
      component={RainmanDemo}
      durationInFrames={2295}
      fps={VIDEO.fps}
      width={VIDEO.width}
      height={VIDEO.height}
    />
  );
};
