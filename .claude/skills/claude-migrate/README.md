# claude-migrate

A Claude Code **skill** that migrates an older repo to current conventions
**subtractively** — it shrinks always-on context instead of adding more files.
It rewrites a lean, minimal-sufficient `CLAUDE.md` from the code and relocates
history / procedures / automation out of always-on context into
memory / skills / hooks, measuring the always-on token budget before vs after.

> Design credit: this implements the subtractive-audit proposal — the
> "reward *less*" bias, the deterministic-measurement vs Claude-judgment split,
> "lean on the living built-ins," and the two honest limitations (auto-memory is
> only nudgeable; the platform moves fast). See those reflected below.

## Status — v0.1 (validated, with gaps)

**Proven end-to-end** on a throwaway Python/`unittest` repo: the non-mutating
Diagnose pass, and the full Apply path — dirty-tree refusal, archive-not-delete,
lean rewrite, knowledge relocation (de-dup to a sibling doc + history/constants
to `docs/DECISIONS.md`), verify-loop **no-worse** before/after, and a clean
reviewable diff (~1,022 → ~322 always-on tokens on the test repo).

A real Diagnose output against this repo's own `CLAUDE.md` is committed at
[`docs/claude-migrate-plan.md`](../../../docs/claude-migrate-plan.md) (projected
~4,441 → ~750 tokens) — read it to see exactly what the tool proposes before it
touches anything.

## Install

Copy the `claude-migrate/` folder into either:

- `<your-repo>/.claude/skills/` — available in that repo, or
- `~/.claude/skills/` — available everywhere.

Start a Claude Code session in the repo you want to migrate and run
`/claude-migrate`. (Restart the session if it was already open.)

## How it works (safety model)

```
Diagnose (non-mutating)  →  ⛔ one approval gate  →  Apply (after approval)
```

- **Diagnose** mutates nothing that exists — its only write is a new plan file.
- **Apply** refuses to run on a dirty git tree (so every change is a reviewable
  diff and `git restore .` is a full undo), **archives** the old `CLAUDE.md`
  rather than deleting it, **merges** `settings.json` rather than overwriting,
  and requires the verify loop to be **no worse** after than before.
- Nothing in `CLAUDE.md` is ever dropped silently — every block gets a named
  destination (rule / skill / hook / memory).

## Prerequisites

- A **POSIX `bash`** shell. On **Windows**, run inside **Git Bash or WSL** — the
  measurement and apply steps are bash.
- A **git** repo (the clean-tree precondition is the core safety net).
- **rainman is optional.** Default is off (memory bucket → `docs/DECISIONS.md`).
  Pass `--with-rainman` to backfill history into rainman memory instead.

## Known limits (noted honestly)

1. **Bash-only** — Windows needs Git Bash/WSL (see prerequisites).
2. **Coverage is Python + synthetic.** Validated on a `unittest` project; JS /
   monorepo / "no `CLAUDE.md` at all" are not yet exercised.
3. **Two paths designed but not yet run end-to-end:** the `settings.json`
   hook-**merge** (the test repo proposed no hooks) and the **rainman lane = ON**
   path (validation ran lane-off). Both are low-risk but unproven like the core.
4. **The token number is a rough `chars/4` estimate**, and the optional
   `/context` · `/memory` reconciliation is a heuristic cross-check, not a parser
   to depend on (it's the most format-fragile seam as the platform evolves).
5. **Auto-memory is only nudgeable, not enforceable** ahead of time — Apply can
   enable + curate it (rainman's salience gate), but can't guarantee what a
   future session learns.
