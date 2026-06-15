#!/usr/bin/env python3
"""
Semantic-lane retrieval-lift measurement
========================================

Isolates what the OPTIONAL semantic lane (M7, rainman[semantic] / model2vec)
adds, measured DETERMINISTICALLY — no LLM, no agent, fully reproducible.

The metric is *answer-bearing recall*: for each query, does the card containing
the answer make it into the top-k recalled context? We measure it twice — with
pure LEXICAL recall and with LEXICAL+SEMANTIC recall — over a store that also
holds distractor cards, so retrieval has to find the right one among noise.

Why retrieval (not task success): the agent-level effect ("the model uses the
injected memory") is already shown in quillpay_demo.py (0/6 -> 6/6). The open
question the semantic lane answers is upstream — *does the right card surface
at all* when the query shares no words with it. That's what this measures.

Tasks are worded so a fair lexical retriever genuinely misses (no shared stems),
plus control tasks whose answer is in NO card (to confirm the lane doesn't
hallucinate a retrieval). Honest by construction — including any misses.

    python eval/local_demo/semantic_lift.py            # the measurement
    python eval/local_demo/semantic_lift.py --contexts # show what was recalled

Still synthetic and small-N — NOT the SWE-bench task-success number (../swebench/).
"""

import argparse
import os
import re
import tempfile

from rainman.core.engine import RainmanEngine
from rainman.eval.agent_harness import AgentTask, build_memory_context

# Answer-bearing cards (worded to NOT share stems with their task) + distractors.
MEMORIES = [
    ("convention", "Inbound webhook signatures are verified from the X-Quill-Trace header using HMAC-SHA512 (not SHA-256).", ["src/webhooks/verify.py"]),
    ("convention", "The settlement cron must run at 03:17 UTC to dodge the partner bank's batch window.", ["ops/cron/settlement.txt"]),
    ("failure", "Staging deploys go to cluster qp-stg-7 in eu-central-1; us-east-1 silently drops events.", ["deploy/staging.yaml"]),
    ("convention", "To validate a request token call verify_quill_sig(req, scope='charge'); standard JWT libraries are not used.", ["src/auth/verify.py"]),
    ("decision", "chargeV1 is deprecated; new code must call quill.charge_v2.submit(idempotency_key=...).", ["src/charge/api.py"]),
    ("convention", "The charge retry budget is exactly 5 attempts with a fixed 400ms backoff and no jitter.", ["src/charge/client.py"]),
    # distractors (plausible, same domain, irrelevant to the tasks):
    ("note", "Refunds older than 180 days require manual finance approval.", ["src/refunds.py"]),
    ("note", "PII fields are encrypted via the KMS key alias quill-pii.", ["src/crypto.py"]),
    ("note", "The fraud model scores 0-1000 and blocks anything above 850.", ["src/fraud.py"]),
    ("note", "Rate cards cache in Redis under the rate: prefix with a 600s TTL.", ["src/pricing.py"]),
]

# (id, category, prompt, expected-tokens that prove the answer card was recalled)
TASKS = [
    ("s1", "synonym", "How do we authenticate incoming payment callbacks?", ["x-quill-trace", "sha512"]),
    ("s2", "synonym", "When does the nightly payout batch job kick off?", ["03:17"]),
    ("s3", "synonym", "Which region hosts our pre-production environment?", ["eu-central-1"]),
    ("s4", "synonym", "What function checks a caller's authorization before processing a payment?", ["verify_quill_sig"]),
    ("s5", "synonym", "What is the current API for recording a brand-new transaction?", ["charge_v2", "submit"]),
    ("s6", "synonym", "What is the cap on re-sending a payment that initially failed, and the pause between sends?", ["5", "400ms"]),
    ("c1", "control", "What HTTP status code means 'Too Many Requests'?", ["429"]),
    ("c2", "control", "What does the HTTP 404 status code mean?", ["not found"]),
]


def seed_engine():
    tmp = tempfile.mkdtemp(prefix="semantic_lift_")
    e = RainmanEngine(project_dir=os.path.join(tmp, "p"), global_dir=os.path.join(tmp, "g"))
    e.store.init_project(os.path.join(tmp, "p"))
    e.store.init_global()
    for cat, content, refs in MEMORIES:
        e.add(content, category=cat, file_refs=refs)
    return e


def _present(token, text):
    text = (text or "").lower()
    tok = token.lower()
    for m in re.finditer(re.escape(tok), text):
        b = text[m.start() - 1] if m.start() > 0 else " "
        a = text[m.end()] if m.end() < len(text) else " "
        if not b.isalnum() and not a.isalnum():
            return True
    return False


def _answer_recalled(context, expected):
    return all(_present(e, context) for e in expected)


def build_cases(provider, k: int = 3):
    e = seed_engine()
    cases = []
    for tid, cat, prompt, expected in TASKS:
        t = AgentTask(id=tid, prompt=prompt)
        lex = build_memory_context(e, t, k=k)                          # pure lexical
        sem = build_memory_context(e, t, k=k, semantic_provider=provider)  # +semantic
        cases.append({
            "id": tid, "category": cat, "prompt": prompt, "expected": expected,
            "lexical_context": lex, "semantic_context": sem,
            "lexical_hit": _answer_recalled(lex, expected),
            "semantic_hit": _answer_recalled(sem, expected),
        })
    return cases


def measure(k: int = 3):
    from rainman.semantic import load_provider
    provider = load_provider()
    if provider is None:
        print("No semantic provider installed. Install the extra to run this:")
        print("    pip install 'rainman[semantic]'")
        return 2
    print(f"Provider: {provider.name}   (answer-bearing recall@{k}, deterministic)\n")
    cases = build_cases(provider, k=k)
    print(f"{'task':5} {'cat':9} {'LEXICAL':>8} {'SEMANTIC':>9}")
    for c in cases:
        print(f"{c['id']:5} {c['category']:9} "
              f"{('hit' if c['lexical_hit'] else 'miss'):>8} "
              f"{('hit' if c['semantic_hit'] else 'miss'):>9}")

    def agg(cat):
        rows = [c for c in cases if c["category"] == cat]
        return sum(r["lexical_hit"] for r in rows), sum(r["semantic_hit"] for r in rows), len(rows)
    sl, ss, sn = agg("synonym")
    cl, cs, cn = agg("control")
    print("\nSYNONYM queries (no shared words with their card):")
    print(f"  lexical recall {sl}/{sn}  ->  +semantic recall {ss}/{sn}   "
          f"(the lane recovered {ss - sl} of {sn - sl} lexical misses)")
    print("CONTROL queries (answer is in NO card):")
    print(f"  lexical {cl}/{cn}  semantic {cs}/{cn}   "
          f"(both 0 = the lane doesn't hallucinate a retrieval)")
    misses = [c["id"] for c in cases if c["category"] == "synonym" and not c["semantic_hit"]]
    if misses:
        print(f"\nHonest misses (semantic also failed to surface the card): {misses}")
    print("\n(Synthetic, small-N, retrieval-only — NOT a SWE-bench task-success number.)")
    return 0


def _cmd_contexts(k: int = 3):
    from rainman.semantic import load_provider
    provider = load_provider()
    for c in build_cases(provider, k=k):
        print(f"### {c['id']} [{c['category']}]: {c['prompt']}  (expect {c['expected']})")
        print(f"  lexical  hit={c['lexical_hit']}: {(c['lexical_context'] or '(nothing)')[:160]}")
        print(f"  semantic hit={c['semantic_hit']}: {(c['semantic_context'] or '(nothing)')[:160]}\n")


def main(argv=None):
    ap = argparse.ArgumentParser(description="Semantic-lane retrieval-lift measurement")
    ap.add_argument("--contexts", action="store_true", help="Show recalled contexts per task.")
    ap.add_argument("-k", type=int, default=3, help="top-k recalled context size (default 3).")
    a = ap.parse_args(argv)
    if a.contexts:
        _cmd_contexts(a.k)
        return 0
    return measure(a.k)


if __name__ == "__main__":
    raise SystemExit(main())
