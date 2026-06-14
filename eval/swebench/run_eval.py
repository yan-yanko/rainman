#!/usr/bin/env python3
"""
SWE-bench memory-lift entrypoint.

Thin CLI over ``rainman.eval.agent_harness``. Ships the protocol + a mock dry
run; produces a real number ONLY when you wire in a real agent and dataset (see
README.md). It will not print a headline lift in mock mode.

    python eval/swebench/run_eval.py --dry-run     # prove the plumbing (MOCK)
"""

import argparse
import sys
import tempfile

from rainman.core.engine import RainmanEngine
from rainman.eval.agent_harness import (
    AgentTask,
    KeywordMockAgent,
    compare_memory_on_off,
)


def _dry_run() -> int:
    """Prove the on/off plumbing with a deterministic mock agent + seeded memory.

    This is NOT a benchmark result — the mock resolves a task iff the injected
    memory contains the fix hint, so it trivially shows a lift. It exists only
    to demonstrate the harness is wired correctly end-to-end.
    """
    tmp = tempfile.mkdtemp()
    engine = RainmanEngine(project_dir=f"{tmp}/project", global_dir=f"{tmp}/global")
    engine.store.init_project(f"{tmp}/project")
    engine.store.init_global()

    # Seed prior project memory: a past failure->fix that's relevant to task t1.
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
    # Mock resolves t1 iff memory mentions "refresh-then-compare"; t2 never.
    agent = KeywordMockAgent(hints={"t1": "refresh-then-compare"})

    report = compare_memory_on_off(engine, tasks, agent)
    print("[MOCK] plumbing check — NOT a benchmark result")
    print(f"[MOCK] tasks={report['n']}  "
          f"off={report['off_resolved']}/{report['n']}  "
          f"on={report['on_resolved']}/{report['n']}  "
          f"delta={report['delta_pp']:+.1f}pp")
    print(f"[MOCK] newly resolved with memory: {report['newly_resolved']}")
    print("\nWire in a real agent + SWE-bench Verified to produce a real number "
          "(see README.md).")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Rainman SWE-bench memory-lift harness")
    parser.add_argument("--dry-run", action="store_true",
                        help="Prove the plumbing with a mock agent (no real result).")
    parser.add_argument("--dataset", help="Path to SWE-bench instances (real run).")
    args = parser.parse_args(argv)

    if args.dry_run:
        return _dry_run()

    if not args.dataset:
        print("No --dataset provided. This harness does not fabricate results.\n"
              "Run with --dry-run to verify the plumbing, or wire in a real agent\n"
              "and dataset as described in eval/swebench/README.md.", file=sys.stderr)
        return 2

    print("Real-run wiring is intentionally left to you: implement AgentProtocol\n"
          "and load the dataset into AgentTask records, then call\n"
          "rainman.eval.agent_harness.compare_memory_on_off(). See README.md.",
          file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
