# Rainman integrations — works with any AI coding tool

Rainman is **host-agnostic**. Its core makes zero LLM calls and knows nothing
about any specific editor. There are three ways it plugs in, and every AI coding
tool can use at least one:

| Surface | What it gives you | Where it works |
|---|---|---|
| **MCP tools** (pull) | The model calls `recall` / `remember` / `context` / `links` / `status` when relevant | **Any MCP client** — Cursor, VS Code/Copilot, Windsurf, Cline, Zed, Continue, Claude Code, … |
| **Hooks** (push) | Auto-inject context at session start, re-inject after compaction, learn from every edit | **Claude Code** (its hook lifecycle) |
| **Git post-commit** (push) | Auto-learn from every commit, whatever made it | **Any editor** (it's a git hook) |
| **CLI `--format`** (pull) | Pipe recalled memory into any tool or script | **Anything with a shell** (aider, Makefiles, CI) |

> The zero-LLM, stdlib-only, local, MIT core is identical everywhere. Only the
> *integration adapter* differs per host — and they're thin.

## The 30-second version

```bash
pip install rainman            # (or: pip install -e . from source)

# 1. Print the MCP config for your editor (paste it where it says):
rainman mcp-config --host cursor      # or vscode | windsurf | cline | zed | continue

#    …or let Rainman write the project-local ones for you:
rainman setup --host cursor           # writes .cursor/mcp.json

# 2. Auto-learn from commits in ANY editor:
rainman setup --host git              # installs .git/hooks/post-commit
```

`rainman mcp-config` with no `--host` prints the generic snippet and lists every
supported host.

---

## MCP hosts (pull — the model calls the tools)

Rainman's MCP server (`python -m rainman serve`) speaks standard MCP, so any
MCP-capable client can use its five tools. Configure once; the model then calls
`recall`/`remember`/etc. itself.

### Cursor
`rainman setup --host cursor` writes `.cursor/mcp.json` (project). Global
alternative: `~/.cursor/mcp.json`.
```json
{ "mcpServers": { "rainman": { "command": "python", "args": ["-m", "rainman", "serve"] } } }
```

### VS Code (GitHub Copilot agent)
`rainman setup --host vscode` writes `.vscode/mcp.json`. Open Copilot Chat →
Agent mode → the Rainman tools are available. Note the wrapper key is `servers`:
```json
{ "servers": { "rainman": { "command": "python", "args": ["-m", "rainman", "serve"] } } }
```

### Windsurf
Global config `~/.codeium/windsurf/mcp_config.json` (or Settings → MCP):
```json
{ "mcpServers": { "rainman": { "command": "python", "args": ["-m", "rainman", "serve"] } } }
```

### Cline (VS Code)
Cline → MCP Servers → Configure → `cline_mcp_settings.json` (extension global
storage), same `mcpServers` shape as above.

### Zed
Zed `settings.json` — note Zed **nests** the command under `context_servers`:
```json
{ "context_servers": { "rainman": { "command": { "path": "python", "args": ["-m", "rainman", "serve"] } } } }
```

### Continue
`~/.continue/config.yaml` (`mcpServers`). Continue's config is YAML; the JSON
from `rainman mcp-config --host continue` maps 1:1 — see docs.continue.dev.

### Any other MCP client
`rainman mcp-config` (no host) prints the generic `mcpServers` shape most
clients accept.

---

## Claude Code (full auto-surfacing — push)

Claude Code is the one host with a hook lifecycle, so it gets the full push
experience on top of MCP:

```bash
rainman setup        # registers MCP + installs SessionStart / PostToolUse / SessionEnd hooks
```

- **SessionStart** injects project memory at the top of every session and
  re-injects relevant memory after context compaction.
- **PostToolUse** auto-learns from your Read/Edit/Write/Bash actions.
- **SessionEnd** mines the transcript for decisions/patterns/failures.

The behaviour lives in `rainman/integration/core.py`; the hooks are thin
adapters, so this is the reference for what a full-featured host adapter does.

---

## Auto-learn in ANY editor (git — push)

No hook system? Use the git one. It captures each commit as project memory
(salience-gated, secret-redacted, deduped), regardless of which editor made it.

```bash
rainman setup --host git     # installs .git/hooks/post-commit  ->  rainman learn-commit
```

Commit messages are classified automatically (`fix` → solution, `revert` →
failure, `refactor`/`migrate` → decision, else note). Trivial commits
(wip/merge/typo/bump) are skipped. Run `rainman learn-commit` manually anytime.

---

## aider / plain CLI / scripts (pull via `--format`)

aider has no MCP or hooks, but it can read files and run commands — so pipe
Rainman's memory in:

```bash
# Feed the current working context into an aider session:
aider --read <(rainman context --format md)

# Or pull task-specific memory on demand from aider's /run:
/run rainman recall "auth token validation" --format plain
```

`--format plain` prints one memory's content per line (drop straight into a
prompt); `--format md` prints markdown bullets. Works for any tool, Makefile, or
CI step that can shell out.

---

## What each host gets

| Host | Recall/remember (MCP) | Auto-inject at start | Auto-learn from edits | Auto-learn from commits |
|---|:---:|:---:|:---:|:---:|
| Claude Code | ✅ | ✅ (hooks) | ✅ (hooks) | ✅ (git) |
| Cursor / VS Code / Windsurf / Cline / Zed / Continue | ✅ | via MCP pull | — | ✅ (git) |
| aider / CLI | via `--format` | via `--format` | — | ✅ (git) |

"Auto-inject at start" for MCP hosts means the model can call `context`/`recall`
itself — it's pull, not an unconditional push. The git hook gives every host the
same cross-session auto-learn.
