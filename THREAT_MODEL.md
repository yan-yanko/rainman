# Rainman Threat Model

This document describes what Rainman defends against, how, and what it
deliberately does not. It reflects the implementation as of Phase 1.

## What Rainman is

A local, zero-dependency memory layer for AI coding tools. It stores knowledge
(patterns, solutions, failures, decisions) and surfaces relevant memories into
an AI agent's context — automatically at session start / after compaction, and
on explicit `recall`. Storing and ranking are pure local computation; no data
leaves the machine.

## Assets

1. **Developer secrets** that could be captured by auto-learn (API keys,
   credentials, tokens in files or command output).
2. **Integrity of the AI's context** — the memories injected into an agent
   shape what it does. Corrupted memory means a corrupted agent.
3. **The audit trail** — the record of who taught the AI what.

## Trust boundary — the primary threat

> **Memory is a prompt-injection persistence channel.**

Recalled memories are injected directly into an AI agent's context. Two paths
bring **attacker-influenceable content** into memory:

- `rainman ingest` stores third-party content **verbatim** — git commit
  messages, repo files. A malicious commit message or a planted file can carry
  instructions ("ignore previous instructions and …").
- The `post_tool_use` auto-learn hook records summaries of files read and
  command output, which an attacker who controls a repo can shape.

Once such content is stored, it can be injected into a future session's context
without anyone re-reading the source — the dangerous part. The attacker also
controls the text that drives keyword matching, so they can target the memory
at likely queries.

### Why ranking is not the defense

An attacker controls the memory's content, which feeds the keyword score
(0.35 of the composite). Any fixed ranking penalty on low-trust memories can be
out-stuffed by keyword-engineering the content to score high. Rainman's scoring
also has feedback amplifiers — rehearsal (up to 2×/2.5×) and a two-phase
associative boost — that a surfaced poisoned memory would otherwise ride.

So **ranking is treated as a quality heuristic, never a security boundary.**

## Controls

### 1. Trust levels (`rainman/core/trust.py`)

Every memory has a trust level derived from its `source`:

| Level    | Sources                          | Meaning                          |
|----------|----------------------------------|----------------------------------|
| `user`   | `cli`, `mcp`, empty/legacy       | deliberately stored by a person  |
| `hook`   | `hook:*`                         | auto-learned from the dev's session |
| `ingest` | `ingest:*`, `git:*`              | third-party content, stored verbatim |

Unknown/empty maps to `user`: we positively classify the attacker-controlled
paths (`ingest`/`hook`); legacy memories predate trust and shouldn't be
retroactively penalised.

### 2. Display is unconditional

Every injected memory shows its `trust` and `source` (SessionStart hook, MCP
`recall`, CLI). The model and the human can always discount low-trust content.

### 3. Gating is the security control

- **Auto-injection trust floor.** Unsolicited context injection (SessionStart,
  post-compaction) is the most dangerous path — no query, no user choice — so
  `ingest`-trust memories are held out of it by default
  (`auto_inject_min_trust`, default `hook`). Explicit `recall` can still reach
  them.
- **Recall floor.** `recall_min_trust` (policy) can gate explicit recall too.
- **Quarantine.** With `quarantine_ingest` on, ingested memories are stored but
  **not recallable** until reviewed (review queue is Phase 2).

### 4. Amplifier denial (closes the feedback loop)

- `ingest`-trust memories accrue **no rehearsal** boost (keyword or recency).
- Associative boost **cannot flow from a higher-trust anchor down to a
  lower-trust entry** — a poisoned memory can't ride the credibility of the
  curated knowledge it auto-linked itself to.

### 5. Quality prior (honest, visible, non-security)

A small multiplier (`user` 1.0 / `hook` 0.95 / `ingest` 0.85) nudges ranking as
a tiebreaker. It is surfaced in the `RecallResult` breakdown (`trust_prior`).
Documented as quality, not defense.

### 6. Secret redaction (`rainman/core/redact.py`)

Auto-learn skips sensitive paths and redacts secret-shaped content before
storage. Org policy can add mandatory `extra_redaction_patterns` and
`path_denylist` entries on top of the built-ins.

### 7. Audit log (`rainman/core/audit.py`)

Opt-in, append-only JSONL of store / recall / forget / retention events with
actor and timestamp — for "what was injected during that incident?".

### 8. Policy control plane (`rainman/core/config.py`)

`org.enforce > project > user > org.defaults > builtin`. The `enforce` block
holds mandates lower layers cannot override (e.g. force `quarantine_ingest`,
disable auto-learn, set a recall floor), distributable via MDM or git.

## Residual risk / non-goals

- **A `user`-trust memory is trusted.** If an attacker can run `rainman add`,
  invoke the `mcp` `remember` tool, or write as the developer, they can plant a
  top-trust memory. Rainman assumes the local user and their authenticated
  tools are trusted; OS-level account security is out of scope.
- **Redaction is best-effort.** Novel secret formats may pass; treat it as
  defense-in-depth, not a guarantee. Prefer `path_denylist` for known-sensitive
  files.
- **No memory content signing yet.** Memories are not cryptographically bound to
  their author; the `author` field is provenance, not proof. Signed memories are
  future work (tied to the team sync server).
- **Single-machine identity.** `author` is the local OS user (or
  `RAINMAN_AUTHOR`). Real multi-user identity arrives with the team server.
- **Quarantine review UI** is Phase 2; today quarantined memories are simply
  withheld from recall.
