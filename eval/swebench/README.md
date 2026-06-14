# SWE-bench memory lift harness

The headline proof for Rainman: **does injecting project memory raise a coding
agent's task-success rate?** This directory is the SWE-bench entrypoint for the
`rainman.eval.agent_harness` plumbing.

## What this ships — and what it does NOT

- ✅ The protocol and plumbing: run each task **twice** (memory-on vs
  memory-off), compute the percentage-point lift in resolved tasks.
- ✅ A `--dry-run` mode that proves the wiring with a deterministic mock agent.
- ❌ **No results, no numbers.** A real number requires running a real agent
  over the real dataset on real compute. Nothing here fabricates one.
- ❌ No bundled model or agent. You plug in your own `AgentProtocol`.

This split is deliberate: the metric is only credible if produced against
SWE-bench Verified with a disclosed agent. The harness lives outside the
stdlib-only `rainman/` client (it needs an agent runner + compute), mirroring
the `rainman-server` split.

## Protocol

For each task (e.g. a SWE-bench Verified instance):

1. **memory-off**: run the agent with empty context → resolved? (the baseline)
2. **memory-on**: seed a `RainmanEngine` with the team's/project's prior
   memories, recall the relevant ones for the task (task-state conditioned on
   the failing file + error), inject them as context, run the agent → resolved?
3. Aggregate: `delta_pp = (on_resolved - off_resolved) / n * 100`.

Honest ceilings from the literature (do not exceed without evidence): oracle
experience reuse ≈ +8pp (SWE Context Bench); typed experience cards ≈ +12pp
(Agent KB, arXiv:2507.06229). A credible Rainman result lands in/below that band
**at $0 marginal token cost, fully offline** — which is the differentiator.

## Usage

```bash
# Prove the plumbing with a mock agent (NOT a result):
python eval/swebench/run_eval.py --dry-run

# Real run (you provide the agent + dataset):
#   1. implement AgentProtocol.solve() wrapping your coding agent
#   2. load SWE-bench Verified instances into AgentTask records
#   3. seed the engine with the project's memories
#   4. wire them into run_eval.py and drop --dry-run
```

## Requirements for a real run

- SWE-bench Verified (500 tasks) or Lite (300) — https://www.swebench.com
- A coding agent exposing `solve(task, memory_context) -> bool`
- Compute to run the agent twice per task

Until those are wired, this prints `[MOCK]` and refuses to emit a headline
number.
