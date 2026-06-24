---
name: claude-migrate
description: >-
  Migrate an older repository to current Claude Code conventions — subtractively,
  and safely. Use when a project predates today's CLAUDE.md / skills / hooks
  conventions and feels "not built right for Claude": a bloated or missing
  CLAUDE.md, always-on rules that eat the token budget, no runnable verify loop,
  or months of lost context. This is NOT a checklist of files to add — it shrinks
  always-on context, relocating rules/history/automation out of CLAUDE.md into
  skills/hooks/memory. It runs a non-mutating diagnosis first, emits a full
  migration plan for one approval, and only then rewrites a lean,
  minimal-sufficient CLAUDE.md from the code — measuring the always-on token
  budget before vs after. An optional rainman lane backfills lost context from
  git history. Nothing mutates without approval.
---

# claude-migrate

Bring an old repo up to how Claude Code actually works **today** — by removing,
not adding. Most "Claude-readiness" audits are *additive*: they reward more
commands, more MCP, more hooks, and score a bloated repo as "ready." This tool
is **subtractive**: a lean CLAUDE.md, fewer always-on rules, a low token budget.
It scores *less* higher — with one floor: the lean file must still be
**sufficient** (hard rules + how-to-verify survive).

## The one idea this tool is built on

Being subtractive is only safe if the knowledge you strip has **somewhere to
go**. Otherwise "subtractive" is just amnesia. So the core move is never
*delete* — it's **relocate**: move content from *always-on* context (CLAUDE.md,
paid every turn) to *on-demand* context (a skill, a hook, or memory — paid only
when actually needed). Every step below is an instance of that move — including
what happens to the old CLAUDE.md itself.

## Safety model — READ THIS (the tool can rewrite CLAUDE.md)

This skill can overwrite your project's most important file. It is built so that
it is never destructive and never silent:

1. **Diagnose mutates nothing that exists.** The only write it makes is creating
   one new file — the plan (`docs/claude-migrate-plan.md`). It never edits, moves,
   or deletes anything: not CLAUDE.md, not settings.json, not memory.
   Plan-mode-compatible in spirit — the single new-file write is the deliverable,
   not a mutation of project state. (Non-mutating ≠ zero-write: a fresh advisory
   doc is fully discardable and changes nothing about existing project state.)
2. **Nothing mutates without one explicit approval** of a *complete* plan that
   includes the verbatim proposed CLAUDE.md, the full relocation table, and the
   projected before/after numbers. Approving the plan = approving the exact bytes.
3. **Apply refuses to run on a dirty git tree.** A clean tree is a precondition,
   so every change lands as a reviewable diff and `git restore .` (or a branch
   reset) is a complete undo. Git is the safety net, not the approval prompt.
4. **The old CLAUDE.md is archived, never deleted** — moved to `.claude/archive/`
   (and/or into memory) before the new one is written.
5. **settings.json is merged, never overwritten.** Show the hook diff; abort on
   any conflict rather than clobbering existing hooks.
6. **Proof of no harm.** Capture the verify-loop (tests + lint) result *before*
   apply; it must be **no worse** *after*. Green-before / red-after means the
   migration broke something → stop and surface it; the clean tree makes rollback
   one command.

If any guarantee above can't be met (no git, tree won't come clean, verify loop
can't run), say so and stop — don't proceed in a degraded mode.

## Two modes

`Diagnose (non-mutating)  →  ⛔ one approval gate  →  Apply (after approval)`

Default to **Diagnose only**. Proceed to Apply solely on explicit approval (or
an `--apply` argument that still re-confirms the plan).

---

## Mode 1 — Diagnose (non-mutating)

> The only write in this entire mode is creating one new file — the plan. Nothing
> that already exists is edited, moved, or deleted.

### D1. Measure the baseline (deterministic)

File-based and robust; slash-command output is an optional cross-check, never a
dependency (it's the most format-fragile seam).

```bash
# --- Claude-readiness measurement (rough; chars/4 token estimate) ---
root="${1:-.}"
est() { wc -c | awk '{printf "%d", $1/4}'; }

echo "## Always-on context (paid EVERY turn)"
total=0
for f in CLAUDE.md CLAUDE.local.md .claude/CLAUDE.md; do
  if [ -f "$root/$f" ]; then
    t=$(est < "$root/$f"); total=$((total + t))
    printf "  %-22s ~%6s tok\n" "$f" "$t"
  fi
done
printf "  %-22s ~%6s tok\n" "TOTAL always-on" "$total"

echo "## .claude/ inventory (skills, agents, commands, settings)"
[ -d "$root/.claude" ] && find "$root/.claude" -maxdepth 2 -type f | sort || echo "  (none)"

echo "## Verify loop present? (the most important gap on old repos)"
grep -aiE 'pytest|npm (run )?test|cargo test|go test|make test|ruff|eslint|lint' \
  "$root/CLAUDE.md" "$root/README"* 2>/dev/null | head -3 || echo "  NOT documented — fix first"

echo "## Always-on directive count (heuristic — lower is better)"
grep -aciE '\b(must|never|always|do ?n.t|required|important)\b' "$root/CLAUDE.md" 2>/dev/null

echo "## Exact duplicate non-blank lines in CLAUDE.md"
grep -avE '^\s*$' "$root/CLAUDE.md" 2>/dev/null | sort | uniq -d | head
```

Optionally ask the user to paste `/context` and `/memory` from a fresh session
to reconcile what *actually* loads. If the formats have drifted, trust the
files — don't fail on the parse.

### D2. Draft the migration plan (judgment — still no mutations)

Read the **code** (not the old CLAUDE.md — that's the bloat) and produce a lean,
minimal-sufficient CLAUDE.md by applying the rubric below — drafted **by hand
from the code**, authored directly *into the plan*. `/init`'s output can serve as
a mental starting structure, but since this mode writes nothing but the plan,
`/init` is **not run here** — and per A3 it is **not run in Apply either**. The
plan's bytes are the single source of truth.

Emit the plan — present it inline **and** save it to `docs/claude-migrate-plan.md`
(a new file; the only write this mode makes). The plan must contain:

- **Before** numbers from D1.
- **The verbatim proposed lean CLAUDE.md**, in full.
- **The relocation table** (every block leaving CLAUDE.md → its destination; see
  rubric). Nothing cut without a named destination.
- **Projected After** numbers.
- **Apply preview**: exactly which files get created / archived / merged, and
  whether the rainman lane is on.

End with: *"Non-mutating run — the only write was creating this plan file.
Approve to apply."* Then STOP.

---

## ⛔ Approval gate

The human reviews the plan. Do not continue to Apply without explicit approval.
If they want changes, revise the plan in Diagnose and re-present — still no
mutations.

---

## Mode 2 — Apply (only after approval)

### A0. Preconditions (refuse if unmet)

- `git rev-parse --is-inside-work-tree` succeeds and `git status --porcelain` is
  **empty**. If dirty: stop and ask the user to commit/stash first.
- Run the verify loop and record the baseline pass/fail set. If it's already
  red, surface that — the "no worse after" check needs an honest baseline.

### A1. Backfill lost context (rainman lane on only — additive)

```bash
rainman init
rainman ingest --git --files     # mine commit history + structure into memory
rainman status
```

### A2. Archive the old CLAUDE.md (move, never delete)

```bash
mkdir -p .claude/archive
[ -f CLAUDE.md ] && cp CLAUDE.md ".claude/archive/CLAUDE.$(date +%Y%m%d).md"
```

### A3. Write the new lean CLAUDE.md

Write the approved content from the plan, **byte-for-byte**. Apply executes the
plan; it does not regenerate or re-decide content. **Do not run `/init` here** —
any generator output would risk diverging from the approved bytes, breaking the
"approving the plan = approving the exact bytes" guarantee.

### A4. Create skills / hooks (additive; merge, don't clobber)

- New skills → `.claude/skills/<name>/SKILL.md`.
- Hooks → **merge** into `.claude/settings.json`; show the diff; abort on conflict.

### A5. Relocate the memory bucket

- **Lane on:** add the hand-written rationale that lived in CLAUDE.md as explicit
  memories (git-derived history was captured in A1):
  ```bash
  rainman add "Chose JSON store over SQLite for zero-dep; SQLite is opt-in" -c decision
  ```
- **Lane off:** append to a non-always-on `docs/DECISIONS.md`. Still a subtractive
  win (out of always-on context); rainman is just the better destination.

### A6. Re-measure, re-verify, present the diff

- Re-run D1 → the "After" column.
- Re-run the verify loop → must be **no worse** than the A0 baseline.
- Present the full `git diff` and the before/after table. Undo = `git restore .`
  or reset the branch.

```
                     before    after
always-on tokens     ~4,200    ~1,150
always-on directives     38         9
duplicate lines           6         0
verify loop              pass      pass    <- must not regress
knowledge relocated        —   23 items → skills/hooks/memory
```

Headline: always-on budget drops with **no knowledge lost** and **no test
regressed** — cost moved from per-turn to per-recall.

---

## The subtractive rubric

Score the migrated repo. **Higher = leaner.** Penalize additive bloat, reward
minimal-sufficient.

Reward (each lowers the always-on cost):
- CLAUDE.md is **minimal-sufficient** — only invariants + how-to-verify are
  always-on; everything else relocated.
- Low always-on token budget.
- Zero duplicate or conflicting rules.
- Procedures live in skills, not always-on prose.
- Automations live in hooks, not "remember to…" prose.
- History/rationale lives in memory (or a non-always-on doc), not CLAUDE.md.

**Sufficiency floor (hard gates — fail regardless of leanness):**
- The verify loop (test + lint command) is documented and runnable.
- The genuine hard rules (invariants that, if broken, break the project) are
  present in CLAUDE.md.

The floor is why "less is better" can't degenerate into an empty file. You can
push *close* to minimal precisely because the overflow has a home — memory.

### Relocation buckets

| Bucket | What goes here | Where it lands |
|--------|----------------|----------------|
| **rule** | true always-on invariant ("never add a dependency") | stays in CLAUDE.md |
| **skill** | a multi-step procedure you repeat | `.claude/skills/<name>/SKILL.md` |
| **hook** | an automation ("after editing, run X") | `.claude/settings.json` hook |
| **memory** | history, rationale, "we tried X and it broke", gotchas | rainman (lane on) / `docs/DECISIONS.md` (lane off) |

Most prunable content is **memory** — it's not a rule, skill, or hook; it's recall.

## rainman lane (optional, gated)

The skill is useful **without** rainman: it still does the lean rewrite, the
skill/hook relocation, and the before/after measurement, sending memory-bucket
content to `docs/DECISIONS.md`. rainman is the opt-in *deepening* for the
context-retention half:

- **on** → A1 backfill + A5 `rainman add` + `rainman setup` to wire
  salience-gated, redacted, trust-leveled auto-learn hooks.
- **off** → memory bucket → `docs/DECISIONS.md`; skip A1 and the setup step.

Enable when the user passes `--with-rainman`, or auto-detect with
`command -v rainman`. Default **off** so the migration tool stays lean and never
forces an external install on someone who only wants the scaffolding pass. (This
mirrors rainman's own architecture, where the semantic lane is opt-in.)

## Limits (be honest in the report)

1. **Auto-memory is not enforceable ahead of time.** Wiring the hooks can only
   enable and nudge curation ("don't record facts discoverable from the code" —
   what rainman's salience gate already enforces); it can't guarantee what gets
   learned. Stated, not hidden.
2. **Version fragility.** rainman's recall/data substrate is external stdlib and
   ages slowly, but its *hook wiring* rides the same versioned Claude Code hook
   surface everything else does — not immune. And the D1 slash-command
   reconciliation is the most format-fragile step; that's why it's a cross-check,
   not a dependency.
