#!/usr/bin/env python3
"""
SWE-bench (and any benchmark) memory-lift entrypoint.

Runs each task twice — memory-OFF and memory-ON — and reports the
percentage-point lift in resolved tasks. Turnkey: you bring a tasks file, an
(optional) memories file, and your agent by dotted path; no script editing.

    # prove the plumbing with a mock agent (NOT a result):
    python eval/swebench/run_eval.py --dry-run

    # real run — your agent, your tasks, your project's memories:
    python eval/swebench/run_eval.py \
        --tasks tasks.jsonl \
        --memories project_memories.jsonl \
        --agent my_pkg.my_agent:SweAgent

Formats (JSON Lines, one object per line):
  tasks.jsonl     {"id": "...", "prompt": "...", "files": [...], "error": "..."}
  memories.jsonl  {"content": "...", "category": "solution", "file_refs": [...]}

Your agent is any object/class with:  solve(task, memory_context: str) -> bool
(see example_agent.py). It is run once per task per arm; `memory_context` is ""
for the memory-off arm. This harness ships NO results and NO bundled model —
running it against a real dataset with a real agent is what produces a number.
"""

import argparse
import importlib
import json
import os
import sys
import tempfile

from rainman.core.engine import RainmanEngine
from rainman.eval.agent_harness import (
    AgentTask,
    KeywordMockAgent,
    compare_memory_on_off,
)


def load_tasks(path):
    tasks = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            d = json.loads(line)
            tasks.append(AgentTask(
                id=str(d["id"]), prompt=d["prompt"],
                files=d.get("files", []), error=d.get("error", ""),
            ))
    return tasks


def seed_memories(engine, path):
    n = 0
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            d = json.loads(line)
            if engine.add(d["content"], category=d.get("category", "note"),
                          file_refs=d.get("file_refs"), tags=d.get("tags")):
                n += 1
    return n


def load_agent(spec):
    """Import an agent from 'module.path:attr'. If attr is a class, instantiate it.

    The current dir and this script's dir are added to sys.path so both your own
    package (run from your repo) and the bundled example_agent.py resolve.
    """
    if ":" not in spec:
        raise SystemExit("--agent must be 'module.path:attr' (e.g. my_pkg.agent:SweAgent)")
    for d in (os.getcwd(), os.path.dirname(os.path.abspath(__file__))):
        if d not in sys.path:
            sys.path.insert(0, d)
    mod_name, attr = spec.split(":", 1)
    obj = getattr(importlib.import_module(mod_name), attr)
    agent = obj() if isinstance(obj, type) else obj
    if not hasattr(agent, "solve"):
        raise SystemExit(f"{spec} has no .solve(task, memory_context) method")
    return agent


def _engine():
    tmp = tempfile.mkdtemp(prefix="swebench_lift_")
    e = RainmanEngine(project_dir=os.path.join(tmp, "p"), global_dir=os.path.join(tmp, "g"))
    e.store.init_project(os.path.join(tmp, "p"))
    e.store.init_global()
    return e


def _print_report(report, label=""):
    n = report["n"]
    print(f"{label}tasks={n}  "
          f"memory-OFF {report['off_resolved']}/{n} ({report['off_rate']*100:.1f}%)  "
          f"memory-ON {report['on_resolved']}/{n} ({report['on_rate']*100:.1f}%)  "
          f"lift {report['delta_pp']:+.1f}pp")
    if report["newly_resolved"]:
        print(f"{label}newly resolved with memory: {report['newly_resolved']}")


def _dry_run():
    """Prove the on/off plumbing with a deterministic mock agent + seeded memory.
    NOT a benchmark result — the mock resolves a task iff the injected memory
    contains the fix hint, so it trivially shows a lift."""
    engine = _engine()
    engine.add(
        "Fixed the JWT auth bug: tokens were compared before refresh, causing 401s. "
        "The fix was to refresh-then-compare in the middleware.",
        category="solution", file_refs=["src/auth/middleware.py"],
    )
    tasks = [
        AgentTask(id="t1", prompt="users get 401 after token refresh",
                  files=["src/auth/middleware.py"], error="HTTP 401 Unauthorized"),
        AgentTask(id="t2", prompt="unrelated css layout flicker on resize",
                  files=["src/ui/grid.css"]),
    ]
    agent = KeywordMockAgent(hints={"t1": "refresh-then-compare"})
    report = compare_memory_on_off(engine, tasks, agent)
    print("[MOCK] plumbing check — NOT a benchmark result")
    _print_report(report, label="[MOCK] ")
    print("\nWire in a real agent + dataset to produce a real number (see README.md).")
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(description="Rainman memory-lift harness")
    p.add_argument("--dry-run", action="store_true", help="Prove the plumbing with a mock agent.")
    p.add_argument("--tasks", help="JSONL of tasks {id, prompt, files?, error?}.")
    p.add_argument("--memories", help="JSONL of project memories to seed {content, category?, file_refs?}.")
    p.add_argument("--agent", help="Agent as 'module.path:attr' with solve(task, memory_context)->bool.")
    p.add_argument("-k", type=int, default=5, help="memories injected per task (default 5).")
    p.add_argument("--json", action="store_true", help="Emit the full report as JSON.")
    args = p.parse_args(argv)

    if args.dry_run:
        return _dry_run()

    if not args.tasks or not args.agent:
        print("Provide --tasks and --agent for a real run (or --dry-run to test the\n"
              "plumbing). This harness does not fabricate results — see README.md.",
              file=sys.stderr)
        return 2

    engine = _engine()
    seeded = seed_memories(engine, args.memories) if args.memories else 0
    tasks = load_tasks(args.tasks)
    agent = load_agent(args.agent)
    print(f"Seeded {seeded} memories; running {len(tasks)} tasks x2 (off/on)...", file=sys.stderr)

    report = compare_memory_on_off(engine, tasks, agent, k=args.k)
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        _print_report(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
