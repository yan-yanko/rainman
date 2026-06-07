import { useRef } from 'react';
import { motion, useInView } from 'framer-motion';
import {
  Github,
  Terminal,
  Brain,
  ArrowRight,
  Zap,
  Play,
  Search,
  Clock,
  AlertTriangle,
  Link,
  Server,
  Command,
  CheckCircle,
  Globe,
  Monitor,
  Code,
  ChevronRight,
} from 'lucide-react';
import { StaggeredFade } from './components/StaggeredFade';
import { FadeDown } from './components/FadeDown';
import { TerminalHero } from './components/TerminalHero';

function ScoreBar({
  score,
  color,
}: {
  score: number;
  color: string;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const isInView = useInView(ref, { once: true });

  return (
    <div ref={ref} className="w-full h-2 bg-white/5 rounded-full overflow-hidden">
      <motion.div
        className="h-full rounded-full"
        style={{ backgroundColor: color }}
        initial={{ width: 0 }}
        animate={isInView ? { width: `${score * 100}%` } : { width: 0 }}
        transition={{ duration: 1.2, delay: 0.3, ease: 'easeOut' }}
      />
    </div>
  );
}

export default function App() {
  return (
    <div className="min-h-screen flex flex-col bg-deep relative">
      {/* Ambient background */}
      <div className="grid-bg fixed inset-0" />
      <div className="orb orb-1 fixed" />
      <div className="orb orb-2 fixed" />
      <div className="orb orb-3 fixed" />

      {/* Navigation */}
      <nav className="sticky top-0 z-50 flex items-center justify-between px-4 md:px-8 py-4 md:py-6 bg-deep/80 backdrop-blur-md border-b border-white/5">
        {/* Left: logo */}
        <div className="flex items-center gap-3">
          <a href="#" className="text-accent font-bold text-lg tracking-tight">
            rainman
          </a>
        </div>

        {/* Center: nav links */}
        <div className="hidden lg:flex items-center gap-8">
          <a
            href="#story"
            className="text-sm text-white/50 hover:text-white/90 transition-colors"
          >
            Story
          </a>
          <a
            href="#validation"
            className="text-sm text-white/50 hover:text-white/90 transition-colors"
          >
            Validation
          </a>
          <a
            href="#how"
            className="text-sm text-white/50 hover:text-white/90 transition-colors"
          >
            How It Works
          </a>
          <a
            href="#integration"
            className="text-sm text-white/50 hover:text-white/90 transition-colors"
          >
            Integration
          </a>
          <a
            href="#getting-started"
            className="text-sm text-white/50 hover:text-white/90 transition-colors"
          >
            Install
          </a>
          <a
            href="#platforms"
            className="text-sm text-white/50 hover:text-white/90 transition-colors"
          >
            Platforms
          </a>
        </div>

        {/* Right: buttons */}
        <div className="flex items-center gap-3">
          <a
            href="https://github.com/yan-yanko/rainman#quick-start"
            className="hidden sm:block text-sm text-white/60 hover:text-white/90 border border-white/10 px-4 md:px-6 py-2 md:py-2.5 rounded-full transition-colors"
          >
            Install
          </a>
          <a
            href="https://github.com/yan-yanko/rainman"
            target="_blank"
            rel="noopener noreferrer"
            className="px-4 md:px-6 py-2 md:py-2.5 bg-white text-deep text-sm font-medium rounded-full hover:bg-white/90 transition-colors flex items-center gap-2"
          >
            <Github className="w-4 h-4" />
            GitHub
          </a>
        </div>
      </nav>

      {/* Hero Section */}
      <section className="min-h-screen flex flex-col items-center px-4 md:px-8 relative pt-16 md:pt-24">
        <div className="relative z-10 flex flex-col items-center">
          {/* Badge pill */}
          <FadeDown delay={0.1}>
            <div className="mb-4 px-3 md:px-4 py-1.5 md:py-2 border border-white/10 rounded-full flex items-center gap-1.5 md:gap-2 text-xs md:text-sm text-white/50">
              <Terminal className="w-3.5 h-3.5 text-accent" />
              <span className="hidden sm:inline text-white/30">&rarr;</span>
              <Brain className="w-3.5 h-3.5 text-accent hidden sm:inline" />
              <span className="hidden sm:inline text-white/30">&rarr;</span>
              <span>
                <span className="hidden sm:inline">
                  Set up once, remember forever
                </span>
                <span className="sm:hidden">Persistent AI memory</span>
              </span>
              <span className="text-white/30">&rarr;</span>
              <Zap className="w-3.5 h-3.5 text-accent-warm" />
            </div>
          </FadeDown>

          {/* Main heading */}
          <StaggeredFade
            text="Rainman"
            className="max-w-5xl mb-2 md:mb-3 px-4 leading-none text-6xl sm:text-7xl md:text-8xl lg:text-9xl font-bold"
            style={{ color: '#e8e8ed' }}
          />
          <FadeDown delay={0.4}>
            <p className="text-2xl sm:text-3xl md:text-4xl lg:text-5xl font-light tracking-tight text-white/60 text-center mb-3 md:mb-4 px-4">
              Set up once, remembers forever.
            </p>
          </FadeDown>

          {/* Subheading */}
          <FadeDown delay={0.5}>
            <p className="text-center text-white/40 max-w-2xl mb-5 md:mb-6 text-sm md:text-base lg:text-lg px-4 leading-relaxed">
              Persistent memory for AI coding tools. Patterns, failures,
              solutions, decisions — remembered across every session. Zero LLM.
              Zero tokens. Zero dependencies.
            </p>
          </FadeDown>

          {/* CTA Buttons */}
          <FadeDown delay={0.7}>
            <div className="flex flex-col sm:flex-row items-center gap-3 md:gap-4 px-4 mb-8 md:mb-10">
              {/* Primary CTA */}
              <a
                href="#getting-started"
                className="pl-4 md:pl-6 pr-2 py-2 bg-gradient-to-r from-[#2a5a3e] to-[#3a7a5a] text-white rounded-full flex items-center gap-2 hover:opacity-90 transition-opacity text-sm md:text-base"
              >
                <Terminal className="w-4 h-4" />
                Get Started
                <span
                  className="w-7 h-7 md:w-8 md:h-8 rounded-full flex items-center justify-center"
                  style={{
                    background:
                      'linear-gradient(59deg, #3a7a5a 0%, #6ee7b7 100%)',
                  }}
                >
                  <Play className="w-3 h-3 md:w-4 md:h-4 fill-white text-white" />
                </span>
              </a>
              {/* Secondary CTA */}
              <a
                href="https://github.com/yan-yanko/rainman"
                target="_blank"
                rel="noopener noreferrer"
                className="pl-4 md:pl-6 pr-2 py-2 liquid-glass text-white/70 rounded-full flex items-center gap-2 hover:text-white/90 transition-colors text-sm md:text-base"
              >
                View on GitHub
                <span
                  className="w-7 h-7 md:w-8 md:h-8 rounded-full flex items-center justify-center"
                  style={{
                    background:
                      'linear-gradient(59deg, rgba(255,255,255,0.08) 0%, rgba(255,255,255,0.15) 100%)',
                  }}
                >
                  <ArrowRight className="w-3 h-3 md:w-4 md:h-4 text-white" />
                </span>
              </a>
            </div>
          </FadeDown>

          {/* Terminal Animation */}
          <FadeDown delay={0.9}>
            <TerminalHero />
          </FadeDown>
        </div>

        {/* Bottom badges */}
        <FadeDown delay={1.2}>
          <div className="flex items-center justify-center gap-4 md:gap-8 py-8 md:py-12 text-[10px] md:text-xs text-white/25 uppercase tracking-wider">
            <span>124 tests</span>
            <span className="w-1 h-1 rounded-full bg-white/10" />
            <span>0 dependencies</span>
            <span className="w-1 h-1 rounded-full bg-white/10" />
            <span>&lt;1s test suite</span>
            <span className="w-1 h-1 rounded-full bg-white/10" />
            <span>MIT license</span>
          </div>
        </FadeDown>
      </section>

      {/* Section 1: Origin Story */}
      <section id="story" className="py-20 md:py-28 relative z-10">
        <div className="max-w-6xl mx-auto px-4 md:px-8">
          <FadeDown>
            <p className="text-xs uppercase tracking-wider text-accent mb-4">
              Origin Story
            </p>
          </FadeDown>
          <FadeDown delay={0.1}>
            <h2 className="text-3xl md:text-4xl font-semibold text-[#e8e8ed] mb-6">
              Born from a $0 bug that cost hours of debugging
            </h2>
          </FadeDown>
          <FadeDown delay={0.2}>
            <p className="text-white/40 max-w-3xl mb-12 leading-relaxed">
              We were debugging a systematic voting bias in an election predictor.
              The AI assistant declared the problem "unfixable by prompt
              engineering" and spent hours exploring workarounds. The fix already
              existed in the codebase. A 516-line, science-grounded module that
              assigns political identity using ANES/Pew research data — zero LLM
              calls. Built weeks earlier. The AI had full codebase access, 500+
              lines of CLAUDE.md, memory files. It still forgot. Static docs
              describe what things are. They don't activate when needed. That's
              the gap Rainman fills.
            </p>
          </FadeDown>

          {/* Timeline cards */}
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
            {[
              {
                label: 'The Problem',
                title: 'AI declared "unfixable"',
                body: 'Election predictor showed 15-20pp anti-incumbent bias. Claude Code couldn\'t find the existing fix.',
              },
              {
                label: 'The Discovery',
                title: '516 lines, forgotten',
                body: 'political_identity.py — science-grounded, zero-LLM — was already built. Never surfaced.',
              },
              {
                label: 'The Insight',
                title: "Static docs don't activate",
                body: "CLAUDE.md describes what exists. It doesn't fire when the AI needs it. No contextual retrieval.",
              },
              {
                label: 'The Solution',
                title: 'Rainman',
                body: "Persistent memory with scoring-based retrieval. Plugs into Claude Code via MCP + hooks.",
              },
            ].map((card, i) => (
              <FadeDown key={card.label} delay={0.2 + i * 0.1}>
                <div className="liquid-glass rounded-xl p-6 h-full">
                  <p className="text-accent text-xs uppercase tracking-wider mb-2">
                    {card.label}
                  </p>
                  <h3 className="text-[#e8e8ed] font-medium mb-2">
                    {card.title}
                  </h3>
                  <p className="text-white/40 text-sm leading-relaxed">
                    {card.body}
                  </p>
                </div>
              </FadeDown>
            ))}
          </div>
        </div>
      </section>

      {/* Section 2: Validation */}
      <section id="validation" className="py-20 md:py-28 relative z-10">
        <div className="max-w-6xl mx-auto px-4 md:px-8">
          <FadeDown>
            <p className="text-xs uppercase tracking-wider text-accent mb-4">
              Validated
            </p>
          </FadeDown>
          <FadeDown delay={0.1}>
            <h2 className="text-3xl md:text-4xl font-semibold text-[#e8e8ed] mb-6">
              The forgotten module now surfaces as result #1
            </h2>
          </FadeDown>
          <FadeDown delay={0.2}>
            <p className="text-white/40 max-w-2xl mb-12 leading-relaxed">
              Tested on the same codebase where the problem was discovered. 307
              memories ingested from git history, file structure, and manual
              learnings.
            </p>
          </FadeDown>

          {/* Validation cards */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {[
              {
                query: 'rainman recall "election voting bias"',
                result:
                  'political_identity.py — the exact module that was "forgotten"',
                score: 0.937,
                color: '#6ee7b7',
              },
              {
                query: 'rainman recall "political identity assignment"',
                result:
                  'RLHF bias failure + political_identity.py reference',
                score: 0.97,
                color: '#6ee7b7',
              },
              {
                query: 'rainman recall "CEP migrate claude sonnet"',
                result:
                  'CEP calibration warning — DO NOT migrate without re-validation',
                score: 0.891,
                color: '#f59e0b',
              },
              {
                query: 'rainman recall "cognitrait personality memory"',
                result: 'CogniTrait description + related engine files',
                score: 0.867,
                color: '#f59e0b',
              },
            ].map((item, i) => (
              <FadeDown key={i} delay={0.2 + i * 0.1}>
                <div className="liquid-glass rounded-xl p-6">
                  <div className="bg-black/40 rounded-lg p-3 mb-4 font-mono text-sm text-white/70">
                    $ {item.query}
                  </div>
                  <p className="text-[#e8e8ed] text-sm mb-3">{item.result}</p>
                  <div className="flex items-center gap-3">
                    <ScoreBar score={item.score} color={item.color} />
                    <span
                      className="text-sm font-mono font-medium"
                      style={{ color: item.color }}
                    >
                      {item.score.toFixed(3)}
                    </span>
                  </div>
                </div>
              </FadeDown>
            ))}
          </div>
        </div>
      </section>

      {/* Section 3: How It Works */}
      <section id="how" className="py-20 md:py-28 relative z-10">
        <div className="max-w-6xl mx-auto px-4 md:px-8">
          <FadeDown>
            <p className="text-xs uppercase tracking-wider text-accent mb-4">
              Scoring Engine
            </p>
          </FadeDown>
          <FadeDown delay={0.1}>
            <h2 className="text-3xl md:text-4xl font-semibold text-[#e8e8ed] mb-6">
              Four signals, zero LLM
            </h2>
          </FadeDown>
          <FadeDown delay={0.2}>
            <p className="text-white/40 max-w-2xl mb-12 leading-relaxed">
              Every memory gets a composite score from four components. No
              embeddings, no API calls — keyword matching, math, and cognitive
              science.
            </p>
          </FadeDown>

          {/* 2x2 grid */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {[
              {
                icon: Search,
                title: 'Keyword Match',
                body: 'Overlap between query and memory content, tags, and file references. Rehearsal boost for frequently accessed memories.',
                weight: '0.35',
              },
              {
                icon: Clock,
                title: 'Temporal Decay',
                body: 'ACT-R power-law decay with 14-day half-life. Recently accessed memories stay fresh. Old unused memories fade.',
                weight: '0.25',
              },
              {
                icon: AlertTriangle,
                title: 'Importance',
                body: "Failures score 0.9, solutions 0.8, decisions 0.7. Extra boost for keywords like 'critical', 'bug', 'fix'.",
                weight: '0.20',
              },
              {
                icon: Link,
                title: 'Associative',
                body: 'Memories auto-link by keyword overlap. Recalling one boosts its neighbors. Two-phase retrieval surfaces the graph.',
                weight: '0.20',
              },
            ].map((card, i) => (
              <FadeDown key={card.title} delay={0.2 + i * 0.1}>
                <div className="liquid-glass rounded-xl p-6 h-full">
                  <div className="flex items-center justify-between mb-4">
                    <div className="flex items-center gap-3">
                      <card.icon className="w-5 h-5 text-accent" />
                      <h3 className="text-[#e8e8ed] font-medium">
                        {card.title}
                      </h3>
                    </div>
                    <span className="text-accent font-mono text-sm">
                      w: {card.weight}
                    </span>
                  </div>
                  <p className="text-white/40 text-sm leading-relaxed">
                    {card.body}
                  </p>
                </div>
              </FadeDown>
            ))}
          </div>
        </div>
      </section>

      {/* Section 4: Integration */}
      <section id="integration" className="py-20 md:py-28 relative z-10">
        <div className="max-w-6xl mx-auto px-4 md:px-8">
          <FadeDown>
            <p className="text-xs uppercase tracking-wider text-accent mb-4">
              Integration
            </p>
          </FadeDown>
          <FadeDown delay={0.1}>
            <h2 className="text-3xl md:text-4xl font-semibold text-[#e8e8ed] mb-12">
              MCP + Hooks. Plug and play.
            </h2>
          </FadeDown>

          {/* MCP + CLI cards */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-6">
            <FadeDown delay={0.2}>
              <div className="liquid-glass rounded-xl p-6 h-full">
                <span className="inline-block text-xs uppercase tracking-wider text-accent-blue bg-accent-blue/10 px-2 py-1 rounded mb-3">
                  MCP Server
                </span>
                <h3 className="text-[#e8e8ed] font-medium mb-2">
                  5 tools for Claude Code
                </h3>
                <p className="text-white/40 text-sm mb-4 leading-relaxed">
                  recall, remember, context, links, status. Claude searches your
                  memory before declaring anything unsolvable.
                </p>
                <div className="bg-black/40 rounded-lg p-4 font-mono text-sm text-white/70">
                  $ claude mcp add rainman -- python -m rainman serve
                </div>
              </div>
            </FadeDown>
            <FadeDown delay={0.3}>
              <div className="liquid-glass rounded-xl p-6 h-full">
                <span className="inline-block text-xs uppercase tracking-wider text-accent-blue bg-accent-blue/10 px-2 py-1 rounded mb-3">
                  CLI
                </span>
                <h3 className="text-[#e8e8ed] font-medium mb-2">
                  Full command line
                </h3>
                <p className="text-white/40 text-sm mb-4 leading-relaxed">
                  init, add, recall, status, links, context, ingest, export,
                  serve. Works standalone or alongside MCP.
                </p>
                <div className="bg-black/40 rounded-lg p-4 font-mono text-sm text-white/70 space-y-1">
                  <p>$ rainman add "Fixed OOM on Railway — use semaphore(2)"</p>
                  <p>$ rainman recall "memory limits deployment"</p>
                  <p>$ rainman links "political_identity.py"</p>
                </div>
              </div>
            </FadeDown>
          </div>

          {/* Killer feature callout */}
          <FadeDown delay={0.4}>
            <div className="liquid-glass rounded-xl p-6 border border-accent/20 mb-6">
              <div className="flex items-start gap-4">
                <div className="w-10 h-10 rounded-lg bg-accent/10 flex items-center justify-center flex-shrink-0 mt-1">
                  <Zap className="w-5 h-5 text-accent" />
                </div>
                <div>
                  <h3 className="text-[#e8e8ed] font-medium text-lg mb-2">
                    PostCompact: The Killer Feature
                  </h3>
                  <p className="text-white/40 text-sm leading-relaxed">
                    When Claude's context gets compacted during long sessions,
                    memories disappear. Rainman's PostCompact hook fires at
                    exactly that moment — it reads the compaction summary, recalls
                    relevant knowledge, and re-injects it into Claude's fresh
                    context. The one moment everything gets lost is the one moment
                    Rainman activates.
                  </p>
                </div>
              </div>
            </div>
          </FadeDown>

          {/* Hook cards */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <FadeDown delay={0.5}>
              <div className="liquid-glass rounded-xl p-6 h-full">
                <span className="inline-block text-xs uppercase tracking-wider text-accent-warm bg-accent-warm/10 px-2 py-1 rounded mb-3">
                  SessionStart Hook
                </span>
                <h3 className="text-[#e8e8ed] font-medium mb-2">
                  Context from day one
                </h3>
                <p className="text-white/40 text-sm leading-relaxed">
                  Every new session starts with your project's top memories
                  loaded. Claude knows what exists before you ask.
                </p>
              </div>
            </FadeDown>
            <FadeDown delay={0.6}>
              <div className="liquid-glass rounded-xl p-6 h-full">
                <span className="inline-block text-xs uppercase tracking-wider text-accent-warm bg-accent-warm/10 px-2 py-1 rounded mb-3">
                  PostToolUse Hook
                </span>
                <h3 className="text-[#e8e8ed] font-medium mb-2">
                  Auto-learn silently
                </h3>
                <p className="text-white/40 text-sm leading-relaxed">
                  When Claude reads a file, edits code, or runs tests — Rainman
                  records it. No manual input. Knowledge accumulates.
                </p>
              </div>
            </FadeDown>
          </div>
        </div>
      </section>

      {/* Section 5: Getting Started */}
      <section id="getting-started" className="py-20 md:py-28 relative z-10">
        <div className="max-w-6xl mx-auto px-4 md:px-8">
          <FadeDown>
            <p className="text-xs uppercase tracking-wider text-accent mb-4">
              Getting Started
            </p>
          </FadeDown>
          <FadeDown delay={0.1}>
            <h2 className="text-3xl md:text-4xl font-semibold text-[#e8e8ed] mb-12">
              30 seconds. Three commands.
            </h2>
          </FadeDown>

          {/* Steps */}
          <div className="space-y-8 mb-12">
            {/* Step 1 */}
            <FadeDown delay={0.2}>
              <div className="flex gap-6">
                <div className="flex-shrink-0 w-10 h-10 rounded-full bg-accent/10 border border-accent/30 flex items-center justify-center text-accent font-mono font-bold">
                  1
                </div>
                <div className="flex-1">
                  <h3 className="text-[#e8e8ed] font-medium mb-2">Install</h3>
                  <p className="text-white/40 text-sm mb-4">
                    Pure Python, zero dependencies. Works on any OS with Python
                    3.10+.
                  </p>
                  <div className="bg-black/40 rounded-lg p-4 font-mono text-sm text-white/70">
                    $ pip install git+https://github.com/yan-yanko/rainman.git
                  </div>
                </div>
              </div>
            </FadeDown>

            {/* Step 2 */}
            <FadeDown delay={0.3}>
              <div className="flex gap-6">
                <div className="flex-shrink-0 w-10 h-10 rounded-full bg-accent/10 border border-accent/30 flex items-center justify-center text-accent font-mono font-bold">
                  2
                </div>
                <div className="flex-1">
                  <h3 className="text-[#e8e8ed] font-medium mb-2">Setup</h3>
                  <p className="text-white/40 text-sm mb-4">
                    One command configures everything — initializes storage,
                    registers the MCP server with Claude Code, installs all three
                    hooks, and creates your project config.
                  </p>
                  <div className="bg-black/40 rounded-lg p-4 font-mono text-sm text-white/70 space-y-1">
                    <p>$ rainman setup</p>
                    <p className="text-accent">
                      &#10003; Storage initialized at .rainman/
                    </p>
                    <p className="text-accent">
                      &#10003; MCP server registered with Claude Code
                    </p>
                    <p className="text-accent">
                      &#10003; Hooks installed (SessionStart, PostCompact,
                      PostToolUse)
                    </p>
                    <p className="text-accent">
                      &#10003; Project config created
                    </p>
                  </div>
                </div>
              </div>
            </FadeDown>

            {/* Step 3 */}
            <FadeDown delay={0.4}>
              <div className="flex gap-6">
                <div className="flex-shrink-0 w-10 h-10 rounded-full bg-accent/10 border border-accent/30 flex items-center justify-center text-accent font-mono font-bold">
                  3
                </div>
                <div className="flex-1">
                  <h3 className="text-[#e8e8ed] font-medium mb-2">Verify</h3>
                  <p className="text-white/40 text-sm mb-4">
                    Self-test confirms engine, persistence, hooks, and MCP
                    integration are all working.
                  </p>
                  <div className="bg-black/40 rounded-lg p-4 font-mono text-sm text-white/70 space-y-1">
                    <p>$ rainman doctor</p>
                    <p className="text-accent">&#10003; Scoring engine</p>
                    <p className="text-accent">&#10003; Memory persistence</p>
                    <p className="text-accent">&#10003; Associative links</p>
                    <p className="text-accent">&#10003; Hook registration</p>
                    <p className="text-accent">&#10003; MCP server</p>
                    <p className="text-accent">&#10003; Config valid</p>
                    <p className="mt-2 text-white/50">
                      14 passed, 0 failed
                    </p>
                  </div>
                </div>
              </div>
            </FadeDown>
          </div>

          {/* Callout */}
          <FadeDown delay={0.5}>
            <div className="liquid-glass rounded-xl p-6 border border-white/10">
              <h3 className="text-[#e8e8ed] font-medium mb-2">
                Set up once. Remember forever.
              </h3>
              <p className="text-white/40 text-sm leading-relaxed">
                No re-activation between sessions. No manual input. Rainman's
                hooks fire automatically every time a session starts, every time
                context compacts, every time a tool runs. Memories persist on disk
                and grow with every session.
              </p>
            </div>
          </FadeDown>
        </div>
      </section>

      {/* Section 6: Platform Support */}
      <section id="platforms" className="py-20 md:py-28 relative z-10">
        <div className="max-w-6xl mx-auto px-4 md:px-8">
          <FadeDown>
            <p className="text-xs uppercase tracking-wider text-accent mb-4">
              Platform Support
            </p>
          </FadeDown>
          <FadeDown delay={0.1}>
            <h2 className="text-3xl md:text-4xl font-semibold text-[#e8e8ed] mb-12">
              Works with your editor.
            </h2>
          </FadeDown>

          {/* Platform cards */}
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4 mb-8">
            {[
              {
                name: 'Claude Code',
                desc: 'Full integration — hooks + MCP',
                highlight: true,
              },
              { name: 'Cursor', desc: 'MCP server + rules file', highlight: false },
              { name: 'Windsurf', desc: 'MCP server', highlight: false },
              { name: 'Continue.dev', desc: 'MCP server', highlight: false },
              { name: 'Copilot', desc: 'MCP server', highlight: false },
              { name: 'Any MCP Client', desc: 'JSON-RPC 2.0 stdio', highlight: false },
            ].map((platform, i) => (
              <FadeDown key={platform.name} delay={0.2 + i * 0.05}>
                <div className="liquid-glass rounded-xl p-6 h-full">
                  <h3 className="text-[#e8e8ed] font-medium mb-1">
                    {platform.name}
                  </h3>
                  <p
                    className={
                      platform.highlight
                        ? 'text-accent text-sm'
                        : 'text-white/40 text-sm'
                    }
                  >
                    {platform.desc}
                  </p>
                </div>
              </FadeDown>
            ))}
          </div>

          <FadeDown delay={0.5}>
            <p className="text-white/30 text-sm leading-relaxed max-w-3xl">
              The core engine and MCP server work with any MCP-compatible client.
              Claude Code gets the deepest integration with automatic hooks for
              session start, context compaction, and tool usage. CLI works
              standalone everywhere.
            </p>
          </FadeDown>
        </div>
      </section>

      {/* Section 7: CTA + Footer */}
      <section className="py-20 md:py-28 relative z-10">
        <div className="max-w-6xl mx-auto px-4 md:px-8 text-center">
          <FadeDown>
            <h2 className="text-3xl md:text-4xl font-semibold text-[#e8e8ed] mb-8">
              Stop losing what you've already built.
            </h2>
          </FadeDown>
          <FadeDown delay={0.1}>
            <div className="inline-block bg-black/40 rounded-lg px-6 py-3 font-mono text-sm text-white/70 mb-8">
              pip install git+https://github.com/yan-yanko/rainman.git && rainman setup
            </div>
          </FadeDown>
          <FadeDown delay={0.2}>
            <div className="flex flex-col sm:flex-row items-center justify-center gap-4">
              <a
                href="https://github.com/yan-yanko/rainman"
                target="_blank"
                rel="noopener noreferrer"
                className="px-6 py-3 bg-white text-deep text-sm font-medium rounded-full hover:bg-white/90 transition-colors flex items-center gap-2"
              >
                <Github className="w-4 h-4" />
                View on GitHub
              </a>
              <a
                href="#"
                className="px-6 py-3 border border-white/10 text-white/60 text-sm rounded-full hover:text-white/90 hover:border-white/20 transition-colors"
              >
                Back to top
              </a>
            </div>
          </FadeDown>
        </div>
      </section>

      {/* Footer */}
      <footer className="relative z-10 border-t border-white/5 py-8">
        <div className="max-w-6xl mx-auto px-4 md:px-8 text-center">
          <p className="text-white/25 text-sm">
            Rainman — by Yan Yanko. MIT License. Zero LLM. Zero tokens. Runs
            locally.
          </p>
        </div>
      </footer>
    </div>
  );
}
