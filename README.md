# Rainman

[![CI](https://github.com/yan-yanko/rainman/actions/workflows/ci.yml/badge.svg)](https://github.com/yan-yanko/rainman/actions/workflows/ci.yml)

Context-aware project memory for AI coding tools. Remembers what you've built, what failed, what works — and surfaces it when your AI assistant needs it.

**Zero LLM calls. Zero external dependencies. Runs locally.**

No embeddings, no API calls — zero tokens to store and rank memory. Recalled memories are injected as ordinary context (the relevant slice, not your whole history), so they cost normal input tokens only when actually used — fewer than pasting your full CLAUDE.md into every prompt.

> 📈 **New:** see [`docs/WHATS_NEW.md`](docs/WHATS_NEW.md) for what changed this cycle — typed experience cards, on-device curation, task-conditioned + optional-semantic recall, and reproducible evidence ([`eval/`](eval/)).

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
# Install (PyPI package: rainman-memory; the CLI and import stay `rainman`)
pip install rainman-memory

# ...or straight from GitHub
pip install git+https://github.com/yan-yanko/rainman.git

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

# Check installation health
rainman doctor

# Where do my agents keep getting stuck? (your skill/doc backlog, auto-collected)
rainman gaps
```

## Editor Integration

Rainman is **host-agnostic** — it works with any AI coding tool, not just Claude
Code. Its MCP server speaks standard MCP (so any MCP client can use the
`recall` / `remember` / `context` / `links` / `status` tools), and a git
post-commit hook gives cross-session auto-learn in **any** editor. Full guide:
**[INTEGRATIONS.md](INTEGRATIONS.md)**.

```bash
# Print the MCP config for your editor (paste where it says):
rainman mcp-config --host cursor     # or vscode | windsurf | cline | zed | continue
rainman mcp-config                   # generic snippet + the full host list

# …or let Rainman write the project-local config for you:
rainman setup --host cursor          # writes .cursor/mcp.json

# Auto-learn from commits in ANY editor:
rainman setup --host git             # installs .git/hooks/post-commit
```

### Claude Code (full auto-surfacing)

Claude Code is the one host with a hook lifecycle, so it gets push-based
auto-surfacing on top of MCP:

```bash
rainman setup        # MCP + SessionStart/PostToolUse/SessionEnd hooks, one command
```

### Any MCP host (Cursor, VS Code/Copilot, Windsurf, Cline, Zed, Continue)

The model calls Rainman's tools when relevant (pull). Config shapes differ per
host (`mcpServers` vs VS Code's `servers` vs Zed's nested `context_servers`) —
`rainman mcp-config --host <name>` prints the right one. Example (Cursor):

```json
{ "mcpServers": { "rainman": { "command": "python", "args": ["-m", "rainman", "serve"] } } }
```

### aider / CLI / scripts

Pipe memory into any tool with `--format`:

```bash
aider --read <(rainman context --format md)
/run rainman recall "auth token validation" --format plain
```

### Hooks (Claude Code only)

Added automatically by `rainman setup` to `.claude/settings.local.json` — the machine-local, git-ignored file, so hook config never rides along in a committed repo. (To wire it by hand:)

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
    "PostToolUse": [{
      "matcher": "",
      "hooks": [{
        "type": "command",
        "command": "python -m rainman.hooks.post_tool_use"
      }]
    }],
    "SessionEnd": [{
      "matcher": "",
      "hooks": [{
        "type": "command",
        "command": "python -m rainman.hooks.session_end"
      }]
    }]
  }
}
```

| Hook | Event | What It Does |
|------|-------|-------------|
| **SessionStart** | New session / resume / compaction | Loads project context; after compaction, re-injects topical + important memories |
| **PostToolUse** | After Read/Edit/Bash | Auto-learns from file reads, edits, and test runs |
| **SessionEnd** | Session close | Captures key decisions from the conversation transcript |

**Compaction recovery is the killer feature.** When Claude's context gets compacted during long sessions, memories are lost. The SessionStart hook fires at exactly that moment (with `source: compact`), reads the recent transcript to understand the current topic, recalls relevant knowledge, and re-injects it into Claude's fresh context. Your AI picks up where it left off.

## How It Works

### Scoring

Every memory gets a composite score when recalled:

| Component | Weight | What It Does |
|-----------|--------|-------------|
| Keyword | 0.35 | Keyword overlap between query and memory content/tags/files |
| Recency | 0.25 | ACT-R power-law decay (14-day half-life, reset on access) |
| Importance | 0.20 | Category-based (failures=0.9, solutions=0.8) + keyword boost |
| Associative | 0.20 | Boost from being linked to other high-scoring memories |

Rehearsal multipliers are capped (keyword: max 2x, recency: max 2.5x) to prevent frequently-recalled memories from permanently outranking fresh exact matches.

### Two-Phase Retrieval

1. Score all memories without associative boost, find top-K
2. Re-score with associative boost using top-K as anchors — surfaces linked knowledge

This means when you recall a memory about "voting bias", related memories about "RLHF", "political identity", and "election predictor" get boosted too — even if they don't directly match your query.

### Cognitively grounded

Rainman's two-phase spreading activation, power-law decay, and recency+frequency
scoring aren't ad hoc — they're the *reliable* mechanisms of human memory
(Collins & Loftus 1975; Ebbinghaus; ACT-R). It also does episodic→semantic
consolidation, a "sleep" pass with adaptive forgetting, reconsolidation, and a
working-memory buffer. It deliberately omits the one mechanism that makes human
memory *unreliable* — reconstruction, i.e. false memories — which is exactly the
part you'd need an LLM for. See **[COGNITIVE_MODEL.md](COGNITIVE_MODEL.md)** for
the mechanism-by-mechanism map (each with the paper *and* the line of code).

### Layered Storage

```
~/.rainman/              Global (cross-project learnings)
<project>/.rainman/      Project (git-committable, team-shareable)
```

Project memories get a 1.2x relevance boost. Both layers merge on recall. Multi-process writes (hooks + MCP server running simultaneously) are protected by file locking.

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

### Input Validation

All inputs are validated before storage:
- **Content**: Stripped, rejected if < 5 chars, truncated at 5,000 chars
- **Category**: Must be one of the 6 valid categories, falls back to `note`
- **Tags**: Max 20 tags, each max 50 chars
- **File refs**: Max 20 refs, each max 500 chars
- **MCP queries**: Clamped to 500 chars, limit clamped to 1-50

### Smart Dedup

When hooks detect a near-duplicate memory (score > 0.8), they don't create a new entry and don't silently skip it — they **refresh the existing memory's timestamp**. This keeps knowledge fresh without duplicating it. Memories that get re-encountered stay relevant in scoring instead of going stale.

### Source Provenance

Every recall result shows where the memory came from:
```
1. [solution] Fixed OOM on Railway — use semaphore(2)
   score=0.847 layer=project source=hook:session_end
```

Sources include: `cli`, `mcp`, `hook:session_end`, `hook:post_tool_use:Read`, `hook:post_tool_use:Bash`, `git:<hash>`, `ingest:files`.

### Secret Redaction

Auto-learn hooks (PostToolUse, SessionEnd) automatically redact sensitive content before storing:
- **Sensitive file paths** (`.env`, `*.pem`, `credentials*`, `*_rsa*`) are skipped entirely
- **Secret patterns** (AWS keys, GitHub tokens, API keys, PEM headers, bearer tokens) are replaced with `[REDACTED]`

This matters because `.rainman/` is designed to be git-committable. Secrets never enter the memory store.

## Architecture

```
rainman/
  core/
    models.py       Memory + RecallResult dataclasses
    scoring.py      Keyword, temporal decay, importance, associative scoring
    sentiment.py    Keyword-based sentiment classifier (zero LLM)
    engine.py       Core: add, recall, context, links, forget, persist
    store.py        Layered JSON persistence (global + project) with file locking
    redact.py       Secret redaction + path denylist for auto-learn safety
  mcp/
    server.py       MCP stdio server (JSON-RPC 2.0, 5 tools)
  cli/
    commands.py     CLI command implementations (init, add, recall, setup, doctor)
  hooks/
    session_start.py   Load project context + compaction recovery
    post_compact.py    Legacy compaction hook (kept for backward compatibility)
    post_tool_use.py   Auto-learn from file reads, edits, test runs
    session_end.py     Capture key decisions from conversations
  ingest/
    git.py          Parse git log into memories
    files.py        Scan project file tree into memories
  __main__.py       CLI entry point
tests/
  test_scoring.py     Scoring tests
  test_engine.py      Engine tests
  test_sentiment.py   Sentiment tests
  test_hooks.py       Hook tests
  test_mcp.py         MCP protocol tests
  test_cli.py         CLI smoke tests
  test_ingest.py      Ingest tests
  test_regressions.py Regression tests
  test_concurrency.py Concurrency, corruption, input validation tests
```

211 unit tests (incl. a recall@5/MRR retrieval-quality gate). Zero external dependencies. CI runs `ruff check` + `pytest` on Python 3.10/3.11/3.12.

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
rainman setup                             Register hooks + MCP for Claude Code + VS Code
rainman doctor                            Self-diagnosis of installation health
```

## Origin

Rainman's scoring engine was extracted from [CogniTrait](https://github.com/yan-yanko/pygmalion) — a personality-shaped memory system for AI agents. CogniTrait uses Big Five personality traits to modulate retrieval weights. Rainman strips the personality dependencies and uses fixed weights optimized for project knowledge retrieval.

The core algorithms (ACT-R temporal decay, keyword scoring, associative linking) are proven across 40+ CogniTrait unit tests and validated on real-world election prediction, marketing research, and synthetic persona workloads.

## Security

Rainman is local-first by design: **no data leaves your machine** — zero
external API calls, zero telemetry, zero runtime dependencies. (The only
network path is the *opt-in* team-sync client, which talks to a server **you**
run after you explicitly configure a remote; the core is fully offline and the
global layer never leaves your machine.) Secrets are redacted before storage,
and third-party content (`rainman ingest`, auto-learn) is trust-tagged and held
out of unsolicited context injection by default.

Memory-poisoning defense is **gating, not ranking**. For the full model see
[`THREAT_MODEL.md`](THREAT_MODEL.md); for reporting and release verification see
[`SECURITY.md`](SECURITY.md).

## Teams (optional)

Rainman is built for the solo developer first. If you want a team to **share a
repo's memory** — one dev's AI learns, everyone's AI knows — there's a separate,
self-hostable sync server:

```
rainman remote add <server-url> <workspace> --token <token>
rainman sync
```

The server (RBAC, OIDC SSO, audit, encryption at rest, org policy) lives in its
own repo: **[rainman-server](https://github.com/yan-yanko/rainman-server)**
(source-available, BSL 1.1). The client here stays MIT and stdlib-only.

## Requirements

- Python 3.10+
- Zero external dependencies (stdlib only)

## License

MIT
