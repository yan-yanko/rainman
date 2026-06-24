# claude-migrate — Migration Plan (DIAGNOSE output)

> **Read-only run.** Producing this file is the *only* write performed. No source
> file, `settings.json`, or memory was touched. Nothing else happens without your
> approval of this plan.

Target: `rainman` (this repo). rainman lane: **ON** (dogfooding — relocated
rationale goes into rainman's own memory).

---

## 1. Before (measured)

| metric | value |
|---|---|
| always-on tokens (`CLAUDE.md`) | ~4,441 (252 lines) |
| always-on directives (heuristic) | 7 |
| duplicate non-blank lines | 4 (storage-diagram noise) |
| cross-file duplication | **Security** section duplicates `THREAT_MODEL.md` + `SECURITY.md` |
| verify loop documented | yes |

The file is a genuinely good reference doc. That's the problem: ~80% of it is
*reference* (re-derivable from code or living in sibling docs), and reference
is paid on **every turn** when it lives in CLAUDE.md.

---

## 2. Proposed lean CLAUDE.md (verbatim — this is what would be written)

```markdown
# Rainman — Project Instructions

Rainman is a standalone developer-memory tool for AI coding workflows (MCP +
Claude Code hooks): it remembers what you built, what failed, what works, and
surfaces it when relevant. Three load-bearing claims constrain every change:

- **Zero external dependencies — stdlib only.** `pip install rainman` pulls in
  nothing. This is the core security/marketing claim; it is non-negotiable.
- **Zero LLM calls.** Storing, scoring, ranking are keyword matching + math.
- **Runs fully local.** No network, no external API calls.

Python 3.10+. MIT.

## Build & verify (run before every change)

​```bash
pip install -e .          # editable install — hooks import rainman as a package
pytest tests/ -m unit     # 268 unit tests, stdlib only
ruff check rainman/       # CI runs this too
​```

A change isn't done until both are green.

## Hard rules (invariants — violating these breaks the project)

- **Never add a dependency to `rainman/`.** stdlib only, MIT, forever. The ONLY
  exception is the opt-in `rainman[semantic]` extra (a CPU-only local embedding
  model) — never imported at core import time.
- **Zero LLM calls** in store / score / rank.
- **Never break the existing tests** (268+). Run the verify loop above first.
- **Durable writes.** Store uses atomic tmp + `os.replace`; multi-process writes
  (hooks + MCP server) use a lockfile. Don't bypass either.

The team-sync **server** (RBAC, SSO, crypto deps) lives in the separate
`rainman-server` repo (BSL 1.1). This repo is the client and stays MIT +
stdlib-only — that split is what keeps the zero-dep claim intact.

## Where things live

​```
rainman/core/   engine, scoring, store (JSON default / SQLite opt-in), text,
                trust, redact, salience, config — retrieval + safety core
rainman/mcp/    MCP stdio server (5 tools: recall/remember/context/links/status)
rainman/hooks/  session_start, post_tool_use, session_end auto-learn hooks
rainman/cli/    CLI commands (init/add/recall/status/setup/doctor/...)
rainman/ingest/ git + file-tree ingestion
tests/          268 unit tests, all marked `unit`
​```

- **Security model** → `THREAT_MODEL.md` + `SECURITY.md` (redaction, trust levels,
  audit, policy plane). Not duplicated here.
- **Design rationale + tuning constants** (scoring weights, auto-link 0.25,
  2000-cap prune-via-`save_all`, rehearsal caps, two-phase retrieval): in memory,
  surfaced by task-conditioned recall when you edit the relevant file —
  `rainman recall "<topic>"` — or read the code.
```

*(The `​` before each ``` in the block above is a zero-width marker so this plan
renders; the real write uses clean fences.)*

Estimated size: **~750 tokens** (~50 lines).

---

## 3. Relocation table (nothing deleted — every block gets a home)

| Block leaving CLAUDE.md | ~tok | Bucket | Destination |
|---|---:|---|---|
| Annotated file tree (Architecture) | ~1100 | discoverable | the filesystem; replaced by 12-line orientation |
| Per-file `tests/` descriptions | ~400 | discoverable | `tests/` + test names |
| Data Model dataclass | ~250 | discoverable | `core/models.py` |
| Scoring prose + weight rationale | ~600 | **memory** | rainman memory (design rationale) |
| Storage layout diagram | ~120 | discoverable | code / README |
| CLI command list | ~250 | discoverable | `rainman --help` / README |
| Team-sync client contract | ~250 | doc | README / `rainman-server` repo |
| MCP 5-tools table | ~180 | discoverable | `mcp/server.py` / README |
| Hooks table | ~150 | discoverable | `hooks/` / README |
| **Security section (full)** | ~500 | doc (de-dup) | `THREAT_MODEL.md` + `SECURITY.md` (already exist) |
| Common Patterns (API gotchas) | ~350 | **memory** | rainman memory |
| Constants/gotchas (0.25, 2000+`save_all`, caps, sentiment) | ~200 | **memory** | rainman memory (task-conditioned) |
| "What This Project Is" history (CogniTrait story) | ~200 | **memory** | rainman memory (project history) |

Kept always-on: identity + verify loop + 4 invariants + orientation ≈ **~750 tok**.

---

## 4. Projected After

| metric | before | after |
|---|---:|---:|
| always-on tokens | ~4,441 | **~750** (−83%) |
| duplicate lines | 4 | 0 |
| Security duplicated w/ sibling docs | yes | no (pointer) |
| verify loop documented | yes | yes *(must not regress)* |
| knowledge relocated | — | 13 blocks → memory(4) / docs(1 de-dup) / discoverable(8) |

---

## 5. Apply preview (what Mode 2 would do — only on approval)

1. **Precondition:** clean git tree + capture `pytest`/`ruff` baseline (both green).
2. `rainman init && rainman ingest --git --files` — backfill history into memory.
3. Archive `CLAUDE.md` → `.claude/archive/CLAUDE.<date>.md` (move, not delete).
4. Write the lean `CLAUDE.md` from §2.
5. `rainman add` the 4 memory-bucket blocks (rationale, patterns, constants, history).
6. Re-measure (§4) + re-run verify loop (**must be no worse**) + show full `git diff`.

No new skills or hooks are proposed for this repo (procedures here are short).

---

## 6. The one judgment call worth your eyes (highest-risk cut)

Relocating the **tuning constants/gotchas** (auto-link `0.25`, the 2000-cap
prune-via-`save_all` correctness note, rehearsal caps) from always-on rules into
*memory* is the riskiest line in this plan. Rationale: they matter only when you
edit `scoring.py` / `engine.py`, and rainman's task-conditioned recall is built
to surface them exactly then — so paying for them every turn is waste. **But** if
recall misses, an agent could reintroduce e.g. the unbounded-growth bug.

- **Recommended (lane on):** relocate — it's the dogfood-consistent choice, and
  it's the whole thesis (move per-task facts to per-task recall).
- **Conservative variant:** keep a 4-line "Design constants" block in Hard Rules
  (~120 tok). Costs a little always-on budget for belt-and-suspenders.

Pick one before Apply.

---

## Approve to apply

This was read-only — only this plan file was written. Reply to approve (and pick
§6), or ask for plan changes (still no mutations).
