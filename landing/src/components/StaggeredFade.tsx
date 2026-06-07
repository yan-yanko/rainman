import { motion, useInView } from 'framer-motion';
import { useRef } from 'react';
import { cn } from '../lib/utils';

interface StaggeredFadeProps {
  text: string;
  className?: string;
  style?: React.CSSProperties;
}

export function StaggeredFade({ text, className, style }: StaggeredFadeProps) {
  const ref = useRef<HTMLHeadingElement>(null);
  const isInView = useInView(ref, { once: true });

  return (
    <motion.h1
      ref={ref}
      className={cn(
        'text-3xl text-center sm:text-4xl md:text-5xl lg:text-6xl font-normal tracking-tight-custom',
        className,
      )}
      style={style}
    >
      {text.split('').map((char, i) => (
        <motion.span
          key={i}
          initial={{ opacity: 0 }}
          animate={isInView ? { opacity: 1 } : { opacity: 0 }}
          transition={{ duration: 0.3, delay: i * 0.025 }}
        >
          {char}
        </motion.span>
      ))}
    </motion.h1>
  );
}
