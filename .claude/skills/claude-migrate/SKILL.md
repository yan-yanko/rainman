---
name: claude-migrate
description: >-
  Migrate an older repository to current Claude Code conventions — subtractively.
  Use when a project predates today's CLAUDE.md / skills / hooks conventions and
  feels "not built right for Claude": a bloated or missing CLAUDE.md, always-on
  rules that eat the token budget, no runnable verify loop, or months of lost
  context. It rewrites a lean, minimal-sufficient CLAUDE.md from the code,
  relocates history/procedures/automation out of always-on context into
  memory/skills/hooks, and measures the always-on token budget before vs after.
  An optional rainman lane backfills lost context from git history.
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
when actually needed). Every phase below is an instance of that move.

## Operating rules (non-negotiable)

1. **Lean on living built-ins, not hardcoded checks.** Call `/init`, ask the
   user for `/context` and `/memory` output — don't reimplement them. Hardcoded
   feature checks rot every platform release; built-ins and code-reading don't.
2. **Every non-deterministic change is behind a human approval gate.** Deciding
   *what* to prune and *what becomes a rule vs skill vs hook vs memory* is
   Claude's judgment over the repo. Always show before/after and STOP for
   explicit approval before writing.
3. **Measure before and after.** A migration that can't show the always-on
   token budget dropping (with knowledge preserved) didn't happen.
4. **Never drop knowledge silently.** Anything cut from CLAUDE.md must land in a
   named destination (skill / hook / memory / a non-always-on doc) or be listed
   in the report. No quiet deletions.

## Phases

Deterministic phases (1, 5) are bash/measurement. Judgment phases (0?, 2, 3, 4)
read the repo and require approval. Phase 0 and Phase 6 are the optional rainman
lane.

### Phase 0 — Backfill lost context (optional, rainman lane)

Run only if the rainman lane is on (see "rainman lane" below). This captures the
project's history *before* anything is pruned, so the lean rewrite isn't
throwing 18 months of decisions away — they've been banked first.

```bash
rainman init
rainman ingest --git --files     # mine commit history + structure into memory
rainman status                   # confirm what got captured
```

### Phase 1 — Measure the "before" (deterministic)

Establish the baseline. This is the brittle seam, so keep it file-based and
robust; treat slash-command output as an optional cross-check, not a dependency.

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
to reconcile what *actually* loads against this file-based estimate. If the
formats have drifted, trust the files — don't fail on the parse.

Record the numbers. They are the "before" column of the final report.

### Phase 2 — Rewrite CLAUDE.md from the code (judgment → approval)

Do **not** edit the old CLAUDE.md — it's the bloat. Start fresh from the code.

1. Invoke the built-in `/init` (via the Skill tool) to generate a first-pass
   CLAUDE.md from the current codebase. Don't reimplement it.
2. Apply the **subtractive rubric** (below) to that draft: cut everything that
   isn't a true always-on invariant or the verify loop.
3. Diff new vs old. **STOP. Show the diff and the projected token delta. Get
   approval.**

### Phase 3 — Classify the overflow (judgment → approval)

For every block in the *old* CLAUDE.md that didn't survive the lean rewrite,
assign exactly one destination. This is the "rule vs skill vs hook" decision
with a fourth bucket — **memory** — added:

| Bucket | What goes here | Where it lands |
|--------|----------------|----------------|
| **rule** | true always-on invariant ("never add a dependency") | stays in CLAUDE.md |
| **skill** | a multi-step procedure you repeat | `.claude/skills/<name>/SKILL.md` |
| **hook** | an automation ("after editing, run X") | `.claude/settings.json` hook |
| **memory** | history, rationale, "we tried X and it broke", gotchas | rainman (lane on) / `docs/DECISIONS.md` (lane off) |

Most prunable content is **memory** — it's not a rule, skill, or hook; it's
recall. Present the full classification table. **STOP for approval.**

### Phase 4 — Apply (judgment → approval, per write)

Write the approved artifacts:

- New lean CLAUDE.md.
- New skills / hooks as classified.
- **memory bucket, lane on:** add the hand-written rationale that lived in
  CLAUDE.md as explicit memories (git-derived history was already captured in
  Phase 0):
  ```bash
  rainman add "Chose JSON store over SQLite for zero-dep; SQLite is opt-in" -c decision
  ```
- **memory bucket, lane off:** append to a non-always-on `docs/DECISIONS.md`.
  This still wins subtractively (it's out of always-on context) — rainman is
  just the *better* destination (on-demand, task-conditioned recall) when present.

Show each write before making it.

### Phase 5 — Measure the "after" (deterministic)

Re-run the Phase 1 script. Report a before/after table:

```
                     before    after
always-on tokens     ~4,200    ~1,150
always-on directives     38         9
duplicate lines           6         0
verify loop documented   no       yes
knowledge relocated        —   23 items → skills/hooks/memory
```

The headline is the always-on token budget dropping **with no knowledge lost** —
the cost moved from per-turn to per-recall.

### Phase 6 — Hand off auto-memory (optional, rainman lane)

You can't enforce ex-ante what Claude will learn in a session — so don't try.
Just wire the curated auto-memory layer and let it run:

```bash
rainman setup     # registers salience-gated, redacted, trust-leveled auto-learn hooks
```

The most you can do at migration time is *nudge* the write-side logic ("don't
record facts discoverable from the code") — which is what rainman's salience
gate already enforces. Leave it on; let it accumulate.

## The subtractive rubric

Score the migrated repo. **Higher = leaner.** Direction is the whole point:
penalize additive bloat, reward minimal-sufficient.

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
- The genuine hard rules (the invariants that, if broken, break the project)
  are present in CLAUDE.md.

The floor is why "less is better" can't degenerate into an empty file. You can
push *close* to minimal precisely because the overflow has a home — that home is
the memory lane.

## rainman lane (optional, gated)

The skill is useful **without** rainman: it still does the lean rewrite, the
skill/hook relocation, and the before/after measurement, sending memory-bucket
content to `docs/DECISIONS.md`. rainman is the opt-in *deepening* for the
context-retention half:

- **on** → Phase 0 backfill + Phase 6 auto-memory + memory bucket → `rainman add`.
- **off** → memory bucket → `docs/DECISIONS.md`; skip Phases 0 and 6.

Enable when the user passes `--with-rainman`, or auto-detect with
`command -v rainman`. Default to **off** so the migration tool stays lean and
built-in-leaning and never forces an external install on someone who only wants
the scaffolding pass. (This mirrors rainman's own architecture, where the
semantic lane is opt-in for the same reason.)

## Limits (be honest in the report)

1. **Auto-memory is not enforceable ahead of time.** Phase 6 can only enable and
   nudge curation; it can't guarantee what gets learned. Stated, not hidden.
2. **Version fragility.** rainman's recall/data substrate is external stdlib and
   ages slowly, but its *hook wiring* rides the same versioned Claude Code hook
   surface everything else does — it is not immune. And the Phase 1/5 slash-command
   reconciliation is the single most format-fragile step; that's why it's a
   cross-check, not a dependency.
