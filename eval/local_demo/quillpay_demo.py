#!/usr/bin/env python3
"""
Quillpay memory-lift demo
=========================

A small, reproducible demonstration that Rainman's recall changes a coding
agent's answers — using an INVENTED service ("Quillpay") whose facts are
arbitrary and unguessable, so a fresh agent cannot know them and must reach for
standard defaults (which are all wrong here).

This is a *mechanism* demo, not a benchmark. See README.md for the full caveats
(synthetic, N=6, agent-required, NOT SWE-bench, not run in CI).

What it does WITHOUT any LLM (deterministic, runnable anywhere):
  --contexts   seed a real RainmanEngine with the facts and print exactly what
               recall() surfaces for each task (proves the live retrieval path)
  --grade      grade a run file (default: the bundled sample_run.json of the
               actual agent answers we captured) and print the lift table

To produce a FRESH run you bring your own agent: feed each task the prompt alone
(memory-off) and the prompt + its `memory_context` (memory-on), collect the
answers into a run JSON, and `--grade` it. See README.md.
"""

import argparse
import json
import os
import re
import tempfile

from rainman.core.engine import RainmanEngine
from rainman.eval.agent_harness import AgentTask, build_memory_context

HERE = os.path.dirname(os.path.abspath(__file__))
SAMPLE_RUN = os.path.join(HERE, "sample_run.json")

# Invented, unguessable facts. A fresh agent has no way to know these; the
# repo contains none of them, so retrieval is the only path to a correct answer.
FACTS = [
    ("convention", "To validate a request token in this codebase call verify_quill_sig(req, scope='charge'); the standard JWT libraries are deliberately NOT used here.", ["src/auth/verify.py"]),
    ("convention", "The charge API retry budget is exactly 5 attempts with a fixed 400ms backoff and NO jitter; more attempts trips the fraud lock.", ["src/charge/client.py"]),
    ("decision", "chargeV1 is deprecated. All new code MUST submit charges via quill.charge_v2.submit(idempotency_key=...).", ["src/charge/api.py"]),
    ("failure", "Staging deploys go to cluster qp-stg-7 in eu-central-1. Deploying to us-east-1 silently drops settlement events.", ["deploy/staging.yaml"]),
    ("convention", "The settlement cron must run at 03:17 UTC (not midnight) to avoid the partner bank's batch window.", ["ops/cron/settlement.txt"]),
    ("convention", "Inbound webhook signatures are verified from the X-Quill-Trace header using HMAC-SHA512 (not SHA-256).", ["src/webhooks/verify.py"]),
]

# (id, prompt, files, error, expected-tokens). A task is "resolved" iff the
# answer contains every expected token (word-boundary aware, see _present).
TASKS = [
    ("t1", "How do I validate the auth token for an incoming charge request in this service? Name the exact function.", ["src/auth/verify.py"], "", ["verify_quill_sig"]),
    ("t2", "How many retry attempts and what backoff should the charge client use here?", ["src/charge/client.py"], "", ["5", "400ms"]),
    ("t3", "Which API call should new code use to submit a charge in this codebase?", ["src/charge/api.py"], "", ["charge_v2", "submit"]),
    ("t4", "Which cluster and region do we deploy staging to?", ["deploy/staging.yaml"], "", ["qp-stg-7", "eu-central-1"]),
    ("t5", "At what time (UTC) must the settlement cron run?", ["ops/cron/settlement.txt"], "", ["03:17"]),
    ("t6", "How are inbound webhook signatures verified — which header and which HMAC algorithm?", ["src/webhooks/verify.py"], "", ["x-quill-trace", "sha512"]),
]


def seed_engine():
    """A real RainmanEngine seeded with the invented facts (temp dirs)."""
    tmp = tempfile.mkdtemp(prefix="quillpay_demo_")
    engine = RainmanEngine(project_dir=os.path.join(tmp, "p"),
                           global_dir=os.path.join(tmp, "g"))
    engine.store.init_project(os.path.join(tmp, "p"))
    engine.store.init_global()
    for category, content, refs in FACTS:
        engine.add(content, category=category, file_refs=refs)
    return engine


def build_cases(k: int = 3):
    """Each task plus the context Rainman's real recall() surfaces for it."""
    engine = seed_engine()
    cases = []
    for tid, prompt, files, err, expected in TASKS:
        task = AgentTask(id=tid, prompt=prompt, files=files, error=err)
        cases.append({
            "id": tid,
            "prompt": prompt,
            "memory_context": build_memory_context(engine, task, k=k),
            "expected": expected,
        })
    return cases


def _present(token: str, text: str) -> bool:
    """True if ``token`` appears in ``text`` not embedded in a larger alnum run.

    Word-boundary aware so the digit ``5`` matches "exactly 5 attempts" but NOT
    "5xx" / "429" — the loose-substring bug from the first run.
    """
    text = (text or "").lower()
    tok = token.lower()
    for m in re.finditer(re.escape(tok), text):
        before = text[m.start() - 1] if m.start() > 0 else " "
        after = text[m.end()] if m.end() < len(text) else " "
        if not before.isalnum() and not after.isalnum():
            return True
    return False


def grade(answer: str, expected) -> bool:
    """A task is resolved iff every expected token is present in the answer."""
    return all(_present(e, answer) for e in expected)


def score(run: dict) -> dict:
    """Grade a run record {task_id: {"off": str, "on": str}} -> aggregate lift."""
    expected = {tid: exp for tid, _, _, _, exp in TASKS}
    per_task, off_ok, on_ok, newly = [], 0, 0, []
    for tid in (t[0] for t in TASKS):
        answers = run.get(tid, {})
        o = grade(answers.get("off", ""), expected[tid])
        n = grade(answers.get("on", ""), expected[tid])
        off_ok += o
        on_ok += n
        if n and not o:
            newly.append(tid)
        per_task.append({"id": tid, "expected": expected[tid], "off_ok": o, "on_ok": n})
    total = len(TASKS)
    return {
        "n": total,
        "off_resolved": off_ok,
        "on_resolved": on_ok,
        "delta_pp": round((on_ok - off_ok) / total * 100, 1),
        "newly_resolved": newly,
        "per_task": per_task,
    }


def _cmd_contexts():
    print("Rainman recall() context per task (live retrieval, no LLM):\n")
    for c in build_cases():
        print(f"### {c['id']}: {c['prompt']}")
        print(c["memory_context"] or "(nothing recalled)")
        print(f"expected tokens: {c['expected']}\n")


def _cmd_grade(run_path: str):
    with open(run_path, encoding="utf-8") as f:
        run = json.load(f)
    result = score(run)
    print(f"Run: {os.path.basename(run_path)}\n")
    print(f"{'task':5} {'memory-OFF':>11} {'memory-ON':>10}")
    for row in result["per_task"]:
        print(f"{row['id']:5} {('PASS' if row['off_ok'] else 'fail'):>11} "
              f"{('PASS' if row['on_ok'] else 'fail'):>10}")
    n = result["n"]
    print(f"\nmemory-OFF resolved {result['off_resolved']}/{n}   "
          f"memory-ON resolved {result['on_resolved']}/{n}   "
          f"lift +{result['delta_pp']}pp")
    print(f"newly resolved by memory: {result['newly_resolved']}")
    print("\n(Synthetic mechanism demo — NOT a SWE-bench result. See README.md.)")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Quillpay memory-lift demo")
    parser.add_argument("--contexts", action="store_true",
                        help="Print what recall() surfaces per task (no LLM).")
    parser.add_argument("--grade", nargs="?", const=SAMPLE_RUN, default=None,
                        help="Grade a run JSON (default: bundled sample_run.json).")
    args = parser.parse_args(argv)

    if args.contexts:
        _cmd_contexts()
    else:
        _cmd_grade(args.grade or SAMPLE_RUN)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
