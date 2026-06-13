# Rainman — Project Instructions

> Read this before doing anything.

## What This Project Is

Rainman is a standalone developer memory tool that plugs into AI coding workflows via MCP and Claude Code hooks. It remembers what you've built, what failed, what works — and surfaces relevant knowledge when the AI needs it, without being asked.

Zero LLM calls. Runs locally. Zero external dependencies (stdlib only). Storing and ranking memory spends zero tokens; recalled memories are injected as normal context, so they cost input tokens only when actually surfaced to the model.

Built by extracting the scoring engine from CogniTrait (Pygmalion's personality-shaped memory), stripping Big Five personality dependencies, and adapting it for project knowledge retrieval.

**Repo:** `C:\Users\yanko\My Apps\rainman`
**Stack:** Python 3.10+ (stdlib only)
**Tests:** `pip install -e . && pip install ./server && pytest tests/ -m unit` — 238 tests across 19 files. (`./server` brings PyJWT[crypto] for the sync/SSO tests; without it those import-skip/fail.)

## Architecture

```
rainman/
  core/
    models.py       Memory (+ author, .trust property) + RecallResult dataclasses
    scoring.py      Keyword, temporal decay, importance, associative scoring + trust amplifier denial + quality prior
    sentiment.py    Keyword-based sentiment classifier (zero LLM)
    trust.py        Trust levels (user>hook>ingest) derived from source; quality prior
    identity.py     current_actor() — local OS user / RAINMAN_AUTHOR
    engine.py       Core: add, recall, context, links, forget, persist, retention, _visible()
    store.py        JSON backend (default): layered persistence, file locking, fsync, schema_version
    sqlite_store.py SQLite backend (opt-in): WAL, per-layer DB, no 2000-cap, indexed
    storage.py      StorageBackend Protocol + make_store() backend factory
    redact.py       Secret redaction + path denylist (+ org-policy extras) for auto-learn safety
    audit.py        Append-only JSONL audit log (opt-in, batched) — store/recall/forget/retention
    config.py       Policy control plane (org.enforce > project > user > org.defaults > builtin)
    log.py          Structured stdlib logging (RAINMAN_LOG_LEVEL)
  mcp/
    server.py       MCP stdio server (JSON-RPC 2.0, 5 tools)
  cli/
    commands.py     CLI command implementations (init, add, recall, status, setup, doctor)
  hooks/
    session_start.py   Load project context at session start (also handles post-compaction re-injection)
    post_compact.py    Legacy compaction hook (logging only; re-injection moved to session_start)
    post_tool_use.py   Auto-learn from file reads, edits, test runs
    session_end.py     Capture key decisions from conversation transcripts
  sync/
    client.py       SyncClient — push/pull project memories to a sync server (stdlib urllib)
  ingest/
    git.py          Parse git log into memories
    files.py        Scan project file tree into memories
  __main__.py       CLI entry point (argparse)
server/             SEPARATE package (rainman-server) — self-hosted sync server, stdlib-only
  rainman_server/
    db.py           SQLite: seq cursor, tokens (RBAC role), items + tombstones, audit trail
    app.py          ThreadingHTTPServer: sync (pull/push) + admin API, RBAC-enforced, audited
    console.py      Minimal admin web console (HTML+vanilla JS) served at /admin
    oidc.py         OIDC SSO: RS256 JWT validation (PyJWT) + claim->RBAC mapping
    __main__.py     `rainman_server serve` + `token add --role`
  Dockerfile        Container image (stdlib, no pip step)
  DEPLOY.md         Production + air-gapped deploy runbook
SOC2_READINESS.md   Control mapping to SOC 2 Trust Services Criteria + gap list
tests/                  (181 tests total, all marked `unit`)
  test_scoring.py     scoring components + weighted sum
  test_engine.py      add / recall / context / links / forget
  test_sentiment.py   sentiment classifier
  test_hooks.py       session_start, post_compact, post_tool_use, session_end
  test_mcp_server.py  MCP JSON-RPC protocol + tools (incl. error sanitization)
  test_cli_smoke.py   CLI smoke
  test_integration.py end-to-end layering
  test_concurrency.py locking, corruption quarantine, fsync, schema version
  test_regressions.py regression guards
  test_trust.py       trust levels, amplifier denial, quality prior, floors (Ph1a)
  test_audit.py       append-only audit log (Ph1b)
  test_config.py      policy precedence + wired knobs (Ph1c)
  test_retention.py   TTL prune + global-layer save safety (Ph1d)
  test_review.py      quarantine review queue: approve/reject (Ph2c)
  test_sqlite_backend.py  SQLite backend parity, selection, migrate (Ph2a)
  test_sync.py        end-to-end sync over HTTP: push/pull/tombstone/auth (Ph2b)
  test_rbac.py        role enforcement, admin API, audit, token migration (Ph3)
  test_hardening.py   token hashing at rest + audit hash-chain tamper-evidence
  test_oidc.py        OIDC SSO: claim->role mapping, rejection cases, static coexistence
  conftest.py         adds server/ to sys.path for sync tests
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
rainman review [approve|reject] <id>  # Review quarantined memories (Ph2c)
rainman migrate --to sqlite|json      # Switch storage backend (Ph2a)
rainman remote add <url> <ws> --token # Configure sync remote (Ph2b)
rainman sync                          # Push + pull project memories (Ph2b)
```

## Sync server (Phase 2b — separate `server/` package, stdlib-only)

```bash
python -m rainman_server serve --host 0.0.0.0 --port 8787 --db ./sync.db
python -m rainman_server token add --user alice --workspace acme-api --role contributor
```

RBAC (Phase 3): roles `reader` (pull) < `contributor` (pull+push) < `admin`
(manage tokens + audit). Admin console at `/admin`. Centralized audit trail
(push/pull/token/revoke) in the server DB. Deploy: `server/DEPLOY.md` (Docker +
air-gapped); compliance: `SOC2_READINESS.md`. SSO/SAML/SCIM deferred pending a
target IdP; server stays stdlib-only until then.

SSO (OIDC): the server accepts OIDC bearer JWTs from any RS256 IdP alongside
static tokens (`oidc.py`) — JWT-shaped credential → OIDC path, else static
token; both feed the same RBAC model. RS256-pinned (no alg confusion),
`iss`/`aud`/`exp` verified, JWKS or pinned-key. MFA delegated to the IdP. Config
via `RAINMAN_OIDC_*` env. SCIM provisioning not yet built (claims mapped at
login). Server deps now: `cryptography`, `PyJWT[crypto]`.

Server hardening: bearer tokens are stored/looked up as SHA-256 digests only
(`token_digest`) — never cleartext at rest; raw tokens migrate in place. The
audit log is hash-chained (`row_hash = sha256(prev | fields)`); `verify_audit`
/ `GET /v1/admin/audit/verify` detects any altered or deleted row. Encryption
of memory content at rest still relies on host FDE (needs a crypto dep, gated
by the stdlib-only rule).

Syncs the **project layer only** (global is personal). Monotonic-cursor delta
protocol with tombstones; last-write-to-server-wins by `seq`. Bearer token per
seat — stored in `~/.rainman/sync_credentials.json` or `RAINMAN_SYNC_TOKEN`,
**never** the git-committable `.rainman/sync_state.json`. `sync` is push-then-pull
(emit local tombstones before re-pulling). Client `pushed` map is the synced
baseline, updated by both push AND pull (so pulled memories aren't re-uploaded
and resurrected after another client deletes them). SessionStart auto-pulls.

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

See [`THREAT_MODEL.md`](THREAT_MODEL.md) for the full model and [`SECURITY.md`](SECURITY.md) for reporting + release integrity. Summary:

- **Secret redaction:** Auto-learn (post_tool_use, session_end) runs content through `core/redact.py` before storing. Sensitive file paths (.env, *.pem, credentials*) are skipped entirely. Content patterns (AWS keys, GitHub tokens, API keys, PEM headers) are replaced with `[REDACTED]`. Org policy can add mandatory `extra_redaction_patterns` + `path_denylist`.
- **No data leaves the machine.** Zero external API calls, zero network traffic.
- **Trust levels (`core/trust.py`):** every memory has a level (`user` > `hook` > `ingest`) derived from `source`. Memory poisoning defense is **gating, not ranking** (attacker controls keyword content): ingest is held out of unsolicited auto-injection by default; ingest gets no rehearsal/associative amplifiers; `quarantine_ingest` policy can withhold ingested memories until reviewed. A small visible quality prior (`trust_prior`) only nudges ranking.
- **Provenance:** `Memory.author` records the actor; trust + source shown on every injection.
- **Audit log (`core/audit.py`):** opt-in append-only JSONL of store/recall/forget/retention with actor + timestamp.
- **Policy plane (`core/config.py`):** `org.enforce > project > user > org.defaults > builtin`; `enforce` block = non-overridable org mandates.

## Hard Rules

- **Client (`rainman/`) has zero external dependencies.** stdlib only. No pip install needed beyond setuptools. This is non-negotiable — it's the core security/marketing claim.
- **Zero LLM calls.** Storing, scoring, and ranking are keyword matching + math — zero tokens. Recalled memories are injected as normal context, costing input tokens only when surfaced to the model.
- **Never break the existing tests (205 and counting).** Run `pip install -e . && pytest tests/ -m unit` before any change. CI also runs `ruff check rainman/ server/`.
- **Client stays stdlib-only forever; the `server/` package MAY take deps** (decision 2026-06-13). The server is separate, so dependencies there don't touch the client's zero-dep claim. Server deps so far: `cryptography`, `PyJWT[crypto]` (for SSO/OIDC + encryption-at-rest). Never add a dep to `rainman/`.
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
