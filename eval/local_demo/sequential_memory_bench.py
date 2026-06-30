#!/usr/bin/env python3
"""
Sequential same-repo memory benchmark — task-success, non-tautological
======================================================================

The honest task-success test for memory. SWE-bench-style benchmarks use
SELF-CONTAINED tasks (solvable from the repo alone), so injected memory either
does nothing or only "helps" because you pre-seeded the answer (tautology). This
benchmark instead runs a CAUSAL CHAIN of tasks in one codebase, where each later
task depends on knowledge ESTABLISHED by an earlier task in the SAME run.

Crucially, a task's own knowledge is added to the store ONLY AFTER that task
runs (simulating the hook learning from completed work). So when task N runs, the
store holds what tasks 1..N-1 earned — never task N's own answer. The lift is
real, not pre-seeded.

Three arms, identical accumulated knowledge, differing only in RETRIEVAL:

  * no-memory   — prompt only. A fresh agent can't know the project's unguessable
                  conventions and reaches for the (wrong) industry default.
  * file-memory — prompt + a fair grep over the accumulated markdown notes
                  (stopword-filtered whole-word match over content + file paths,
                  ranked by overlap then recency). The "I keep notes and grep
                  them" baseline, steelmanned (it can match filenames too).
  * Rainman     — prompt + engine.recall(), task-state-conditioned on the files
                  in play (M2). Stemming + IDF ranking + file-affinity.

Deterministic, no LLM:
  --dry-run    run all three arms with a MOCK agent (resolves iff the required
               earned-knowledge token is in the injected context). Proves the
               wiring + measures the RETRIEVAL gap end-to-end. NOT a result.
  --contexts   print, per task, exactly what each arm injects (this is what you
               feed real subagents to produce a live number)
  --grade RUN  grade a recorded 3-arm run {task_id: {none, file, rainman}}

A real task-success number needs a real agent (the prompt + each arm's context,
graded by token presence) — produced exactly like quillpay_demo.py's run, but
across the chain. This file ships NO fabricated number.
"""

import argparse
import json
import os
import re
import tempfile

from rainman.core.engine import RainmanEngine
from rainman.eval.agent_harness import AgentTask, build_memory_context

HERE = os.path.dirname(os.path.abspath(__file__))
SAMPLE_RUN = os.path.join(HERE, "sequential_sample_run.json")

# Function words a real person wouldn't grep for (keeps the baseline fair: it
# searches distinctive terms, like a human, not stopword noise).
_STOPWORDS = {
    "the", "a", "an", "is", "are", "do", "does", "how", "why", "what", "i", "to",
    "in", "on", "for", "of", "and", "my", "me", "you", "we", "it", "this", "that",
    "with", "as", "at", "be", "by", "or", "so", "good", "am", "should", "must",
    "same", "way", "rest", "here", "anything", "out", "add", "use", "which",
}

# Pre-existing project noise (seeded into BOTH stores before the chain). Some
# deliberately share words with later queries, so retrieval has to rank, not
# just match.
DISTRACTORS = [
    ("note", "CI runs on ubuntu-24.04 with a 30-minute job timeout", ["ci/config.yml"]),
    ("note", "Feature flags resolve through the LaunchToggle SDK at request time", ["src/flags.py"]),
    ("note", "Thumbnails are generated lazily and pinned to the CDN edge", ["src/media.py"]),
    ("note", "Localization strings sync nightly from the translation service", ["src/i18n.py"]),
    ("note", "The JWT signing key was rotated last quarter across all services", ["ops/keys.md"]),       # shares 'jwt'
    ("note", "Refund analytics dashboards live in Grafana", ["dashboards/refunds.md"]),                   # shares 'refund'
    ("note", "The ledger read-replica lag alert fires above 5 seconds", ["ops/ledger_alert.md"]),         # shares 'ledger'
]

# The causal chain. Each task:
#   requires    — tokens proving the agent used EARLIER-earned knowledge (graded)
#   establishes — (category, content, file_refs) added AFTER the task runs
# T1 establishes; nothing earned yet, so every arm passes it. The deltas live in
# T2..T5, each of which needs something a prior task earned.
CHAIN = [
    {
        "id": "t1",
        "prompt": "Implement request authentication for the new charge endpoint. "
                  "What is the right way to validate a request token in this codebase?",
        "files": ["src/auth/verify.py"],
        "error": "",
        "requires": [],  # first task: no prior knowledge needed
        "establishes": [
            ("convention",
             "Request tokens are validated with verify_quill_sig(req, scope='charge'); "
             "standard JWT libraries are deliberately NOT used in this codebase.",
             ["src/auth/verify.py"]),
        ],
    },
    {
        "id": "t2",
        "prompt": "Build a refund endpoint. It needs to authenticate the caller exactly "
                  "like the charge endpoint does. Which function authenticates the request?",
        "files": ["src/refunds.py", "src/auth/verify.py"],
        "error": "",
        "requires": ["verify_quill_sig"],  # reuse T1's auth convention (not JWT)
        "establishes": [
            ("convention",
             "Refunds older than 180 days require manual finance approval before they can be issued.",
             ["src/refunds.py"]),
        ],
    },
    {
        "id": "t3",
        "prompt": "Write a nightly bulk-refund job that drains the refund queue, applying "
                  "the same eligibility rules as the single refund endpoint.",
        "files": ["src/jobs/bulk_refund.py", "src/refunds.py"],
        "error": "",
        "requires": ["180"],  # apply T2's 180-day approval rule
        "establishes": [
            ("failure",
             "The bulk-refund job deadlocked on the ledger table under concurrency; "
             "fixed by ordering all ledger writes by account_id before committing.",
             ["src/jobs/bulk_refund.py", "src/ledger.py"]),
        ],
    },
    {
        "id": "t4",
        # Prompt shares almost NO words with the T3 failure card. Only Rainman's
        # task-state conditioning (ledger.py overlap) + stemming (concurrent ~
        # concurrency) can surface it; grep on prose alone struggles.
        "prompt": "Add a balance-reconciliation batch that persists adjustments to the "
                  "ledger. Any gotcha with concurrent persistence I should watch for?",
        "files": ["src/jobs/reconcile.py", "src/ledger.py"],
        "error": "",
        "requires": ["account_id"],  # recall T3's earned deadlock fix
        "establishes": [],
    },
    {
        "id": "t5",
        "prompt": "Add an admin endpoint to reverse a settled charge. It has to be "
                  "authenticated, and a reversal counts as a refund so the age rule applies.",
        "files": ["src/admin/reverse.py", "src/auth/verify.py", "src/refunds.py"],
        "error": "",
        "requires": ["verify_quill_sig", "180"],  # needs BOTH T1 and T2 knowledge
        "establishes": [],
    },
]


# --- retrieval arms ----------------------------------------------------------
_WORD = re.compile(r"\w+")


def _grep_context(notes, query: str, k: int) -> str:
    """File-memory baseline: whole-word term match over note content + file
    paths (stopword-filtered), ranked by #matches then recency. `notes` is an
    ordered list of (content, file_refs) — later = more recent."""
    terms = {t for t in _WORD.findall(query.lower()) if len(t) > 2 and t not in _STOPWORDS}
    scored = []
    for idx, (content, refs) in enumerate(notes):
        hay = (content + " " + " ".join(refs)).lower()
        hits = sum(1 for t in terms if re.search(rf"\b{re.escape(t)}\b", hay))
        if hits:
            scored.append((hits, idx, content))
    scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
    top = [c for _, _, c in scored[:k]]
    if not top:
        return ""
    return "Relevant project notes:\n" + "\n".join(f"- {c}" for c in top)


# Realistic store noise: payment-domain memories that SHARE vocabulary with the
# tasks (refund/charge/auth/token/ledger/request/webhook) so they crowd a grep,
# but NEVER contain an answer token (verify_quill_sig / 180 / account_id). This
# is what a real .rainman store looks like after months — not zero-overlap junk.
_NOISE_TEMPLATES = [
    ("note",       "The {dom} dashboard for {reg} refreshes every {n} minutes", ["dashboards/{dom}.md"]),
    ("note",       "{Dom} request latency p99 settled around {n}ms after the cache change", ["src/{dom}/metrics.py"]),
    ("decision",   "Deprecated the legacy {dom} export endpoint in favour of {dom}_v2", ["src/{dom}/api.py"]),
    ("convention", "All {dom} webhooks retry on the standard schedule with jitter", ["src/{dom}/hooks.py"]),
    ("failure",    "A {dom} report job timed out under load; raised the worker pool to {n}", ["src/jobs/{dom}.py"]),
    ("note",       "{Dom} auth tokens are cached for {n} seconds at the edge layer", ["src/{dom}/cache.py"]),
    ("note",       "The {dom} settlement file lands in the {reg} bucket nightly", ["ops/{dom}.txt"]),
    ("note",       "{Dom} requests are rate-limited to {n} per minute at the gateway", ["src/{dom}/gw.py"]),
]
_DOMAINS = ["refund", "charge", "payout", "ledger", "billing", "invoice", "settlement", "webhook"]
_REGIONS = ["eu-central-1", "us-east-1", "ap-south-1"]
_NUMS = [30, 45, 90, 250, 500, 15, 60, 120]  # deliberately excludes 180 (an answer token)


def _noise(n: int):
    """Generate `n` realistic, domain-overlapping noise memories (no answer tokens)."""
    out = []
    i = 0
    while len(out) < n:
        cat, tmpl, refs = _NOISE_TEMPLATES[i % len(_NOISE_TEMPLATES)]
        dom = _DOMAINS[i % len(_DOMAINS)]
        content = tmpl.format(dom=dom, Dom=dom.capitalize(),
                              reg=_REGIONS[i % len(_REGIONS)], n=_NUMS[i % len(_NUMS)])
        out.append((cat, f"{content} [{i}]", [r.format(dom=dom) for r in refs]))
        i += 1
    return out


def _seed():
    """A real engine + a parallel notes list, both holding the distractors."""
    tmp = tempfile.mkdtemp(prefix="seq_bench_")
    engine = RainmanEngine(project_dir=os.path.join(tmp, "p"), global_dir=os.path.join(tmp, "g"))
    engine.store.init_project(os.path.join(tmp, "p"))
    engine.store.init_global()
    notes = []
    for cat, content, refs in DISTRACTORS:
        engine.add(content, category=cat, file_refs=refs)
        notes.append((content, refs))
    return engine, notes


def build_cases(k: int = 5, n_noise: int = 0):
    """Replay the chain in order; capture all three arms' injected context for
    each task BEFORE advancing the store with that task's earned knowledge.

    `n_noise` total noise memories are split into batches injected BEFORE each
    task — simulating unrelated work piling up between sessions, so knowledge
    earned early (e.g. t2's auth convention) is buried under more-recent noise by
    the time a later task (t5) needs it. That ageing is where a grep's recency
    tiebreak stops saving it; Rainman must rank on relevance instead."""
    engine, notes = _seed()
    batch = n_noise // len(CHAIN)
    noise = _noise(n_noise)
    cases = []
    for i, step in enumerate(CHAIN):
        # Intervening activity since the previous task (recent, domain-overlapping).
        for cat, content, refs in noise[i * batch:(i + 1) * batch]:
            engine.add(content, category=cat, file_refs=refs)
            notes.append((content, refs))
        atask = AgentTask(id=step["id"], prompt=step["prompt"],
                          files=step["files"], error=step["error"])
        cases.append({
            "id": step["id"],
            "prompt": step["prompt"],
            "files": step["files"],
            "requires": step["requires"],
            "contexts": {
                "none": "",
                "file": _grep_context(notes, step["prompt"] + " " + " ".join(step["files"]), k),
                "rainman": build_memory_context(engine, atask, k=k),
            },
        })
        # Advance: the work is "done", so its learnings enter BOTH stores.
        for cat, content, refs in step["establishes"]:
            engine.add(content, category=cat, file_refs=refs)
            notes.append((content, refs))
    return cases


# --- grading (token-presence, word-boundary aware) ---------------------------
ARMS = ("none", "file", "rainman")


def _present(token: str, text: str) -> bool:
    text, tok = (text or "").lower(), token.lower()
    for m in re.finditer(re.escape(tok), text):
        before = text[m.start() - 1] if m.start() > 0 else " "
        after = text[m.end()] if m.end() < len(text) else " "
        if not before.isalnum() and not after.isalnum():
            return True
    return False


def grade(answer: str, requires) -> bool:
    return all(_present(tok, answer) for tok in requires)


def score(run: dict) -> dict:
    """Grade a recorded 3-arm run {task_id: {none, file, rainman}}."""
    requires = {s["id"]: s["requires"] for s in CHAIN}
    per_task, resolved = [], {a: 0 for a in ARMS}
    for s in CHAIN:
        tid = s["id"]
        answers = run.get(tid, {})
        row = {"id": tid, "requires": requires[tid]}
        for a in ARMS:
            ok = grade(answers.get(a, ""), requires[tid])
            row[a] = ok
            resolved[a] += ok
        per_task.append(row)
    n = len(CHAIN)
    return {
        "n": n,
        "resolved": resolved,
        "rates": {a: round(resolved[a] / n, 2) for a in ARMS},
        "lift_vs_none_pp": round((resolved["rainman"] - resolved["none"]) / n * 100, 1),
        "lift_vs_file_pp": round((resolved["rainman"] - resolved["file"]) / n * 100, 1),
        "per_task": per_task,
    }


# --- mock agent (dry-run): resolves iff the earned token is in the context ---
def _mock_run(n_noise: int = 0):
    cases = build_cases(n_noise=n_noise)
    run = {}
    for c in cases:
        run[c["id"]] = {a: c["contexts"][a] for a in ARMS}  # answer == the context it saw
    return run


def _approx_tokens(text: str) -> int:
    return max(0, len(text) // 4)  # ~4 chars/token; a label, not a real tokenizer


def context_stats(n_noise: int = 0):
    """Precision of the injected context, which the binary did-it-surface check
    hides: how many items / tokens each arm injects per task. A relevance floor
    (Rainman) prunes to the few that matter; a top-k grep pads to k with weak
    matches, so a real agent must read more noise to find the same fact."""
    cases = build_cases(n_noise=n_noise)
    items = {a: [] for a in ARMS}
    tokens = {a: [] for a in ARMS}
    for c in cases:
        for a in ARMS:
            ctx = c["contexts"][a]
            # count injected memory lines (skip the header), not the prompt
            lines = [ln for ln in ctx.splitlines() if ln.startswith(("- ", "["))]
            items[a].append(len(lines))
            tokens[a].append(_approx_tokens(ctx))
    n = len(cases)
    return {a: {"avg_items": round(sum(items[a]) / n, 1),
                "avg_tokens": round(sum(tokens[a]) / n)} for a in ARMS}


def _print_score(result, header):
    print(header)
    print(f"{'task':5} {'requires':28} {'no-mem':>7} {'file-mem':>9} {'Rainman':>8}")
    print("-" * 62)
    for r in result["per_task"]:
        req = ",".join(r["requires"]) or "(none — establishing)"
        print(f"{r['id']:5} {req[:28]:28} "
              f"{('PASS' if r['none'] else 'fail'):>7} "
              f"{('PASS' if r['file'] else 'fail'):>9} "
              f"{('PASS' if r['rainman'] else 'fail'):>8}")
    n, res = result["n"], result["resolved"]
    print(f"\nresolved:  no-memory {res['none']}/{n}   file-memory {res['file']}/{n}   "
          f"Rainman {res['rainman']}/{n}")
    print(f"Rainman lift:  +{result['lift_vs_none_pp']}pp vs no-memory   "
          f"+{result['lift_vs_file_pp']}pp vs file-memory")


def _cmd_dry_run(n_noise=0):
    result = score(_mock_run(n_noise))
    _print_score(result, f"[MOCK] retrieval-plumbing check (+{n_noise} noise memories) — "
                         "resolves iff the earned token is in the injected context.\n")
    stats = context_stats(n_noise)
    print("\ncontext precision (avg per task — fewer = tighter, less noise to read):")
    for a in ARMS:
        print(f"  {a:9} {stats[a]['avg_items']:>4} items   ~{stats[a]['avg_tokens']:>4} tokens")
    return 0


def _cmd_scale(levels=(0, 50, 200, 500)):
    """Sweep store size. As noise piles up between tasks, the earned card ages;
    a grep's recency tiebreak stops saving it while Rainman ranks on relevance.
    Pure RETRIEVAL (mock) — does the right earned memory still surface?"""
    print("RETRIEVAL at scale — earned-knowledge tasks resolved (t2-t5, of 4), no LLM:\n")
    print(f"{'store size':>12} {'no-mem':>8} {'file-mem':>9} {'Rainman':>8}   "
          f"{'file items':>10} {'rain items':>10}")
    print("-" * 74)
    n_dep = sum(1 for s in CHAIN if s["requires"])
    for lvl in levels:
        r = score(_mock_run(lvl))
        st = context_stats(lvl)
        size = len(DISTRACTORS) + lvl + sum(len(s["establishes"]) for s in CHAIN)
        # count only the dependent (t2-t5) resolutions, not the freebie t1
        dep = {a: sum(1 for row in r["per_task"] if row["requires"] and row[a]) for a in ARMS}
        print(f"{size:>12} {dep['none']:>6}/{n_dep} {dep['file']:>7}/{n_dep} "
              f"{dep['rainman']:>6}/{n_dep}   {st['file']['avg_items']:>10} "
              f"{st['rainman']['avg_items']:>10}")
    print("\n(Deterministic retrieval, no LLM. 'store size' = distractors + noise + earned cards.)")
    return 0


def _cmd_contexts(n_noise=0):
    print("Per-task injected context by arm (live retrieval, no LLM):\n")
    for c in build_cases(n_noise=n_noise):
        print(f"### {c['id']}  (needs: {c['requires'] or '— establishing —'})")
        print(f"    prompt: {c['prompt']}")
        for a in ARMS:
            ctx = c["contexts"][a] or "(nothing)"
            print(f"    [{a}] {ctx}")
        print()
    return 0


def _cmd_grade(run_path):
    with open(run_path, encoding="utf-8") as f:
        run = json.load(f)
    _print_score(score(run), f"Run: {os.path.basename(run_path)}\n")
    print("\n(Synthetic sequential benchmark — real number needs a real agent. See README.md.)")
    return 0


def main(argv=None):
    from rainman.core.encoding import ensure_utf8_io
    ensure_utf8_io()

    p = argparse.ArgumentParser(description="Sequential same-repo memory benchmark")
    p.add_argument("--dry-run", action="store_true", help="Mock-agent plumbing check (no LLM).")
    p.add_argument("--scale", action="store_true", help="Sweep store size 0..500 (retrieval, no LLM).")
    p.add_argument("--distractors", type=int, default=0, help="Noise memories to inject (default 0).")
    p.add_argument("--contexts", action="store_true", help="Print each arm's per-task context.")
    p.add_argument("--grade", nargs="?", const=SAMPLE_RUN, default=None,
                   help="Grade a recorded 3-arm run JSON.")
    a = p.parse_args(argv)

    if a.scale:
        return _cmd_scale()
    if a.contexts:
        return _cmd_contexts(a.distractors)
    if a.grade is not None:
        return _cmd_grade(a.grade)
    return _cmd_dry_run(a.distractors)


if __name__ == "__main__":
    raise SystemExit(main())
