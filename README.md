# Rainman

Context-aware project memory for AI coding tools. Remembers what you've built, what failed, what works — and surfaces it when your AI assistant needs it.

**Zero LLM. Zero tokens. Zero external dependencies. Runs locally.**

## Why This Exists

We were debugging a systematic voting bias in an election predictor. The AI assistant (Claude Code) declared the problem "unfixable by prompt engineering" and spent hours exploring workarounds.

The fix already existed in the codebase — a 516-line, science-grounded module (`political_identity.py`) that assigns party ID using ANES/Pew data without any LLM calls. It was built weeks earlier. The AI forgot it existed.

This wasn't a one-off. Despite having CLAUDE.md (500+ lines), memory files, and full codebase access, the AI couldn't connect "election bias problem" to "existing solution in the codebase." Static documentation describes what things ARE — it doesn't activate when needed.

Rainman fixes this. It's a persistent memory layer with contextual retrieval that plugs into AI coding workflows via MCP and lifecycle hooks.

## Validated

Tested on the same codebase where the problem was discovered (307 memories ingested from git history + file structure + manual learnings):

| Query | #1 Result | Score |
|-------|-----------|-------|
| "election voting bias" | `political_identity.py` — the exact forgotten module | **0.937** |
| "political identity assignment" | RLHF bias failure + `political_identity.py` | **0.970** |
| "CEP migrate claude sonnet" | CEP calibration warning (DO NOT migrate without re-validation) | **0.891** |
| "cognitrait personality memory" | CogniTrait description + related engine files | **0.867** |

The module that was "unfindable" now surfaces as the #1 result in every relevant query.

## Quick Start

```bash
# Install
pip install -e .

# Initialize in your project
cd /your/project
rainman init

# Ingest existing project knowledge
rainman ingest --git --files

# Add memories manually
rainman add "The auth module uses JWT with 30-day expiry" -c pattern -f api/auth.py
rainman add "Fixed: OOM on Railway caused by unbounded asyncio.gather" -c solution

# Search
rainman recall "authentication"
rainman recall "memory leak" -c failure

# Show what Rainman knows
rainman status
rainman context
```

## Claude Code Integration

### MCP Server (recommended)

Register Rainman as an MCP tool provider — Claude gets 5 tools: `recall`, `remember`, `context`, `links`, `status`.

```bash
claude mcp add rainman -- python -m rainman serve
```

Or add to your project's `.mcp.json`:

```json
{
  "mcpServers": {
    "rainman": {
      "type": "stdio",
      "command": "python",
      "args": ["-m", "rainman", "serve"]
    }
  }
}
```

### Hooks

Add to `.claude/settings.json` for automatic memory management:

```json
{
  "hooks": {
    "SessionStart": [{
      "matcher": "",
      "hooks": [{
        "type": "command",
        "command": "python -m rainman.hooks.session_start"
      }]
    }],
    "PostCompact": [{
      "matcher": "auto",
      "hooks": [{
        "type": "command",
        "command": "python -m rainman.hooks.post_compact"
      }]
    }],
    "PostToolUse": [{
      "matcher": "",
      "hooks": [{
        "type": "command",
        "command": "python -m rainman.hooks.post_tool_use"
      }]
    }]
  }
}
```

| Hook | Event | What It Does |
|------|-------|-------------|
| **SessionStart** | New session | Loads project context so Claude starts with knowledge of what exists |
| **PostCompact** | Context compaction | Re-injects relevant memories after context loss (the killer feature) |
| **PostToolUse** | After Read/Edit/Bash | Auto-learns from file reads, edits, and test runs |

**PostCompact is the killer feature.** When Claude's context gets compacted during long sessions, memories are lost. This hook fires at exactly that moment, recalls relevant knowledge, and re-injects it into Claude's fresh context.

## How It Works

### Scoring

Every memory gets a composite score when recalled:

| Component | Weight | What It Does |
|-----------|--------|-------------|
| Keyword | 0.35 | Keyword overlap between query and memory content/tags/files |
| Recency | 0.25 | ACT-R power-law decay (14-day half-life, reset on access) |
| Importance | 0.20 | Category-based (failures=0.9, solutions=0.8) + keyword boost |
| Associative | 0.20 | Boost from being linked to other high-scoring memories |

### Two-Phase Retrieval

1. Score all memories without associative boost, find top-K
2. Re-score with associative boost using top-K as anchors — surfaces linked knowledge

This means when you recall a memory about "voting bias", related memories about "RLHF", "political identity", and "election predictor" get boosted too — even if they don't directly match your query.

### Layered Storage

```
~/.rainman/              Global (cross-project learnings)
<project>/.rainman/      Project (git-committable, team-shareable)
```

Project memories get a 1.2x relevance boost. Both layers merge on recall.

### Memory Categories

| Category | Importance | Use For |
|----------|-----------|---------|
| `failure` | 0.9 | Bugs, regressions, things that broke |
| `solution` | 0.8 | Fixes, workarounds, things that worked |
| `decision` | 0.7 | Architecture choices, trade-offs, "why we did X" |
| `pattern` | 0.6 | Recurring patterns, conventions, idioms |
| `convention` | 0.5 | Style rules, naming conventions |
| `note` | 0.4 | General observations, file descriptions |

### Auto-Linking

New memories automatically link to existing ones when keyword overlap exceeds 25%. This builds an associative graph — when you recall one memory, linked memories get boosted too.

### Auto-Sentiment

Every memory gets automatic sentiment classification using keyword matching (zero LLM). Six categories: positive, negative, neutral, anxious, frustrated, excited. Developer-specific terms included (regression, workaround, hack = frustrated; deployed, shipped, works = positive).

## Architecture

```
rainman/
  core/
    models.py       Memory + RecallResult dataclasses
    scoring.py      Keyword, temporal decay, importance, associative scoring
    sentiment.py    Keyword-based sentiment classifier (zero LLM)
    engine.py       Core: add, recall, context, links, forget, persist
    store.py        Layered JSON persistence (global + project)
  mcp/
    server.py       MCP stdio server (JSON-RPC 2.0, 5 tools)
  cli/
    commands.py     CLI command implementations
  hooks/
    session_start.py   Load project context at session start
    post_compact.py    Re-inject memories after context compaction
    post_tool_use.py   Auto-learn from file reads, edits, test runs
  ingest/
    git.py          Parse git log into memories
    files.py        Scan project file tree into memories
  __main__.py       CLI entry point
tests/
  test_scoring.py   22 scoring tests
  test_engine.py    25 engine tests
  test_sentiment.py 10 sentiment tests
```

57 unit tests. Zero external dependencies. <1s test suite.

## CLI Reference

```
rainman init                              Initialize .rainman/
rainman add "content" [options]           Add a memory
  -c, --category {pattern,solution,failure,decision,convention,note}
  -t, --tag TAG                           Add tag (repeatable)
  -f, --file PATH                         Add file reference (repeatable)
  --global                                Store in global layer
rainman recall "query" [options]          Search memories
  -n, --limit N                           Max results (default: 5)
  -c, --category CATEGORY                 Filter by category
rainman status                            Memory statistics
rainman links <ref>                       Memories linked to a file/concept
rainman context [-n LIMIT]                Current working context
rainman ingest [options]                  Ingest project history
  --git                                   Parse git log
  --files                                 Scan file structure
  --limit N                               Max git commits (default: 50)
  --depth N                               Max directory depth (default: 4)
rainman export                            Dump all as JSON
rainman serve                             Start MCP stdio server
```

## Origin

Rainman's scoring engine was extracted from [CogniTrait](https://github.com/yan-yanko/pygmalion) — a personality-shaped memory system for AI agents. CogniTrait uses Big Five personality traits to modulate retrieval weights. Rainman strips the personality dependencies and uses fixed weights optimized for project knowledge retrieval.

The core algorithms (ACT-R temporal decay, keyword scoring, associative linking) are proven across 40+ CogniTrait unit tests and validated on real-world election prediction, marketing research, and synthetic persona workloads.

## Requirements

- Python 3.10+
- Zero external dependencies (stdlib only)

## License

MIT
