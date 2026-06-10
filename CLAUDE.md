# Rainman — Project Instructions

> Read this before doing anything.

## What This Project Is

Rainman is a standalone developer memory tool that plugs into AI coding workflows via MCP and Claude Code hooks. It remembers what you've built, what failed, what works — and surfaces relevant knowledge when the AI needs it, without being asked.

Zero LLM calls. Runs locally. Zero external dependencies (stdlib only). Storing and ranking memory spends zero tokens; recalled memories are injected as normal context, so they cost input tokens only when actually surfaced to the model.

Built by extracting the scoring engine from CogniTrait (Pygmalion's personality-shaped memory), stripping Big Five personality dependencies, and adapting it for project knowledge retrieval.

**Repo:** `C:\Users\yanko\My Apps\rainman`
**Stack:** Python 3.10+ (stdlib only)
**Tests:** `pip install -e . && pytest tests/ -m unit` — 143 tests across 9 files, <3s

## Architecture

```
rainman/
  core/
    models.py       Memory + RecallResult dataclasses
    scoring.py      Keyword, temporal decay, importance, associative scoring (fixed weights)
    sentiment.py    Keyword-based sentiment classifier (zero LLM)
    engine.py       Core: add, recall, context, links, forget, persist
    store.py        Layered JSON persistence (global + project) with file locking
    redact.py       Secret redaction + path denylist for auto-learn safety
  mcp/
    server.py       MCP stdio server (JSON-RPC 2.0, 5 tools)
  cli/
    commands.py     CLI command implementations (init, add, recall, status, setup, doctor)
  hooks/
    session_start.py   Load project context at session start (also handles post-compaction re-injection)
    post_compact.py    Legacy compaction hook (logging only; re-injection moved to session_start)
    post_tool_use.py   Auto-learn from file reads, edits, test runs
    session_end.py     Capture key decisions from conversation transcripts
  ingest/
    git.py          Parse git log into memories
    files.py        Scan project file tree into memories
  __main__.py       CLI entry point (argparse)
tests/
  test_scoring.py     22 scoring tests
  test_engine.py      25 engine tests
  test_sentiment.py   10 sentiment tests
  test_hooks.py       28 hook tests (session_start, post_compact, post_tool_use, session_end)
  test_mcp.py         18 MCP protocol tests
  test_cli.py         11 CLI smoke tests
  test_ingest.py      10 ingest tests
  test_regressions.py  6 regression tests
```

## Data Model

```python
Memory:
  id: str                    # timestamp + random hex
  content: str               # the knowledge itself
  timestamp: float           # when created
  importance: float          # 0-1, auto-calculated from category + keywords
  category: str              # pattern | solution | failure | decision | convention | note
  sentiment: str             # positive | negative | neutral | anxious | frustrated | excited
  linked_ids: List[str]      # associative graph edges (auto-linked by keyword overlap)
  recall_count: int          # rehearsal count (ACT-R)
  last_recalled: float       # last access time
  tags: List[str]            # user-defined tags
  source: str                # "git:abc123" | "cli" | "mcp" | "hook:post_tool_use" | "ingest:files"
  file_refs: List[str]       # files this memory relates to
  layer: str                 # "project" | "global"
  metadata: Dict[str, Any]
```

## Scoring — Fixed Weights

| Component | Weight | Description |
|-----------|--------|-------------|
| keyword | 0.35 | Keyword overlap (content + tags + file_refs) + rehearsal boost (capped at 2x) |
| recency | 0.25 | ACT-R power-law decay, 14-day half-life (rehearsal capped at 2.5x) |
| importance | 0.20 | Category-based (failure=0.9, solution=0.8, decision=0.7) + keyword boost |
| associative | 0.20 | Graph boost: memories linked to top-scoring results get boosted |

Two-phase retrieval:
1. Score without associative boost -> find top-K
2. Re-score with associative boost using top-K as anchors

Project memories get 1.2x boost over global memories.

Rehearsal multipliers are capped (keyword: max 2x at 10+ recalls, recency: max 2.5x) to prevent rich-get-richer degradation over time.

## Storage — Layered

```
~/.rainman/              Global layer (cross-project)
  memories.json
  config.json

<project>/.rainman/      Project layer (git-committable)
  memories.json
  config.json
```

## CLI Commands

```bash
rainman init                          # Initialize .rainman/ in current directory
rainman add "content" -c pattern      # Add a memory
rainman recall "query" -n 5           # Search memories
rainman status                        # Show statistics
rainman links <ref>                   # Show linked memories
rainman context                       # Show current working context
rainman ingest --git --files          # Ingest git history + file structure
rainman export                        # Dump all as JSON
rainman serve                         # Start MCP stdio server
rainman setup                         # Register hooks + MCP for Claude Code + VS Code
rainman doctor                        # Self-diagnosis of installation health
```

## MCP Server — 5 Tools

| Tool | Description |
|------|-------------|
| recall | Search memories (ALWAYS before declaring a problem unsolvable) |
| remember | Store a new learning |
| context | Get current working context |
| links | Show memories linked to a file or concept |
| status | Memory statistics |

Register: `claude mcp add rainman -- python -m rainman serve`

## Hooks

| Hook | Event | Matcher | What It Does |
|------|-------|---------|-------------|
| session_start.py | SessionStart | startup, resume | Loads project context at session start |
| session_start.py | SessionStart | compact | Re-injects relevant memories after context compaction |
| post_tool_use.py | PostToolUse | (empty) | Auto-learns from Read/Edit/Write/Bash tool usage |
| session_end.py | SessionEnd | (empty) | Captures key decisions from conversation transcripts |

**Important:** Only SessionStart stdout is added to Claude's context. PostToolUse and SessionEnd are silent (side-effect only). PostCompact stdout is NOT injected — compaction recovery is handled via SessionStart with `compact` matcher.

## Security

- **Secret redaction:** Auto-learn (post_tool_use, session_end) runs content through `core/redact.py` before storing. Sensitive file paths (.env, *.pem, credentials*) are skipped entirely. Content patterns (AWS keys, GitHub tokens, API keys, PEM headers) are replaced with `[REDACTED]`.
- **No data leaves the machine.** Zero external API calls, zero network traffic.
- **Prompt injection awareness:** Memory content from third-party sources (git commits, repo files) is stored verbatim — exercise caution with `rainman ingest` on untrusted repos.

## Hard Rules

- **Zero external dependencies.** stdlib only. No pip install needed beyond setuptools.
- **Zero LLM calls.** Storing, scoring, and ranking are keyword matching + math — zero tokens. Recalled memories are injected as normal context, costing input tokens only when surfaced to the model.
- **Never break the 130 existing tests.** Run `pip install -e . && pytest tests/ -m unit` before any change.
- **Atomic writes.** Store uses tmp + os.replace to prevent corruption on crash.
- **File locking.** Multi-process writes (hooks + MCP server) use lockfile to prevent clobbering.
- **Auto-link threshold: 0.25.** New memories auto-link to existing ones if keyword overlap >= 25%.
- **Max memories: 2000.** Auto-prune drops lowest-importance + oldest when exceeded.
- **Sentiment is keyword-based.** Uses 6 categories with developer-specific terms (frustrated, stuck, regression, hack).
- **Rehearsal caps.** Keyword boost capped at 2x, recency boost at 2.5x (10 recalls max effect).

## Common Patterns

- `engine.add()` auto-classifies sentiment, calculates importance, auto-links, and persists immediately
- `engine.recall()` returns `RecallResult` with score breakdown (keyword, recency, importance, associative)
- `engine.context()` needs no query — returns blend of 60% recent + 40% high-importance
- `store.load_all()` merges both layers; `store.save_one()` persists to the correct layer file
- Hooks read JSON from stdin; only SessionStart outputs to stdout (context injection)
- `RecallResult` uses `total_score` (not `score`) for the composite score

## Running Tests

```bash
# First time: editable install required (hooks import rainman as a package)
pip install -e .
pip install pytest

# Run all unit tests
pytest tests/ -m unit
```
