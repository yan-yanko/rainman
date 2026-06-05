# Rainman — Project Instructions

> Read this before doing anything.

## What This Project Is

Rainman is a standalone developer memory tool that plugs into AI coding workflows via MCP and Claude Code hooks. It remembers what you've built, what failed, what works — and surfaces relevant knowledge when the AI needs it, without being asked.

Zero LLM. Zero tokens. Runs locally. Zero external dependencies (stdlib only).

Built by extracting the scoring engine from CogniTrait (Pygmalion's personality-shaped memory), stripping Big Five personality dependencies, and adapting it for project knowledge retrieval.

**Repo:** `C:\Users\yanko\My Apps\rainman`
**Stack:** Python 3.10+ (stdlib only)
**Tests:** `pytest tests/ -m unit` — 57 tests, <1s

## Architecture

```
rainman/
  core/
    models.py       Memory + RecallResult dataclasses
    scoring.py      Keyword, temporal decay, importance, associative scoring (fixed weights)
    sentiment.py    Keyword-based sentiment classifier (zero LLM)
    engine.py       Core: add, recall, context, links, forget, persist
    store.py        Layered JSON persistence (global + project)
  mcp/
    server.py       MCP stdio server (JSON-RPC 2.0, 5 tools)
  cli/
    commands.py     CLI command implementations
  hooks/
    session_start.py   Load project context at session start
    post_compact.py    Re-inject memories after context compaction (killer feature)
    post_tool_use.py   Auto-learn from file reads, edits, test runs
  ingest/
    git.py          Parse git log into memories
    files.py        Scan project file tree into memories
  __main__.py       CLI entry point (argparse)
tests/
  test_scoring.py   22 scoring tests
  test_engine.py    25 engine tests
  test_sentiment.py 10 sentiment tests
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
| keyword | 0.35 | Keyword overlap (content + tags + file_refs) + rehearsal boost |
| recency | 0.25 | ACT-R power-law decay, 14-day half-life |
| importance | 0.20 | Category-based (failure=0.9, solution=0.8, decision=0.7) + keyword boost |
| associative | 0.20 | Graph boost: memories linked to top-scoring results get boosted |

Two-phase retrieval:
1. Score without associative boost -> find top-K
2. Re-score with associative boost using top-K as anchors

Project memories get 1.2x boost over global memories.

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

| Hook | Event | What It Does |
|------|-------|-------------|
| session_start.py | SessionStart | Loads project context at session start |
| post_compact.py | PostCompact | Re-injects relevant memories after compaction |
| post_tool_use.py | PostToolUse | Auto-learns from Read/Edit/Write/Bash tool usage |

## Hard Rules

- **Zero external dependencies.** stdlib only. No pip install needed beyond setuptools.
- **Zero LLM calls.** All scoring is keyword matching + math. No tokens consumed.
- **Never break the 57 existing tests.** Run `pytest tests/ -m unit` before any change.
- **Atomic writes.** Store uses tmp + os.replace to prevent corruption on crash.
- **Auto-link threshold: 0.25.** New memories auto-link to existing ones if keyword overlap >= 25%.
- **Max memories: 2000.** Auto-prune drops lowest-importance + oldest when exceeded.
- **Sentiment is keyword-based.** Uses 6 categories with developer-specific terms (frustrated, stuck, regression, hack).

## Common Patterns

- `engine.add()` auto-classifies sentiment, calculates importance, auto-links, and persists immediately
- `engine.recall()` returns `RecallResult` with score breakdown (keyword, recency, importance, associative)
- `engine.context()` needs no query — returns blend of 60% recent + 40% high-importance
- `store.load_all()` merges both layers; `store.save_one()` persists to the correct layer file
- Hooks read JSON from stdin, output to stdout (PostCompact, SessionStart) or stay silent (PostToolUse)
