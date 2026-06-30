# Quillpay memory-lift demo

A small, **reproducible** demonstration that Rainman's recall actually changes a
coding agent's answers — and a worked example of how to run a memory-ON vs
memory-OFF comparison with your own agent.

> **This is a mechanism demo, not a benchmark.** It shows *"the right memory
> gets recalled and the agent uses it."* It is **not** the SWE-bench number
> (see `../swebench/`). Read the caveats before quoting anything.

## The idea

Invent a service — **Quillpay** — with six arbitrary, unguessable facts (the
exact token-validation function, the retry budget, the staging region, the
settlement cron time, the webhook HMAC algorithm, the current charge API). None
of it exists anywhere in this repo, so a fresh agent **cannot** know it and will
reach for the standard industry default — which is wrong every time.

Seed those facts into a real `RainmanEngine`. Then, for each task, run two fresh
agents (no shared context):

- **memory-OFF** — the task prompt only
- **memory-ON** — the task prompt + exactly what `recall()` surfaces for it
  (file-conditioned, M2)

## Result (captured 2026-06-14, 12 fresh Claude subagents)

```
task   memory-OFF  memory-ON
t1           fail       PASS     verify_quill_sig
t2           fail       PASS     5 attempts / 400ms / no jitter
t3           fail       PASS     quill.charge_v2.submit
t4           fail       PASS     qp-stg-7 / eu-central-1
t5           fail       PASS     03:17 UTC
t6           fail       PASS     X-Quill-Trace / HMAC-SHA512

memory-OFF resolved 0/6   memory-ON resolved 6/6   lift +100.0pp
```

Every blind agent guessed the standard default (JWT, exponential backoff +
jitter, `us-east-1`, midnight cron, SHA-256, Stripe PaymentIntents) — all wrong.
Every memory-fed agent answered correctly, because `recall()` ranked the
correct card **first** for all six tasks. The verbatim answers are in
`sample_run.json`.

## Reproduce

```bash
# 1) See exactly what recall() surfaces per task (live engine, no LLM):
python eval/local_demo/quillpay_demo.py --contexts

# 2) Re-grade the captured agent answers (deterministic, no LLM):
python eval/local_demo/quillpay_demo.py --grade
```

To run a **fresh** experiment with your own agent: build the cases
(`build_cases()` gives each task its `memory_context`), ask your agent each task
twice (prompt alone, then prompt + `memory_context`), collect the answers into a
run file shaped like `sample_run.json` (`{task_id: {"off": ..., "on": ...}}`),
and `--grade <your_run.json>`.

## Grading

`grade()` marks a task resolved iff every expected token appears in the answer,
**word-boundary aware** — so the digit `5` matches "exactly 5 attempts" but not
`5xx`/`429`. (The first run used loose substring matching and produced one
false positive on t2; this is the corrected grader.)

## Companion: `semantic_lift.py` — what the optional semantic lane adds

`quillpay_demo.py` shows *lexical* memory helps an agent. `semantic_lift.py`
isolates the **optional semantic lane** (M7, `rainman[semantic]`/model2vec) and
measures it **deterministically — no LLM, no agent, fully reproducible**: for
synonym queries that share *no words* with their card, does the answer-bearing
card still surface in the top-k? Measured with pure lexical recall vs
lexical+semantic, over a store seeded with distractor cards.

Result with `potion-base-8M` (`python eval/local_demo/semantic_lift.py`):

```
SYNONYM queries (no shared words with their card):
  lexical recall 2/6  ->  +semantic recall 5/6   (recovered 3 of 4 lexical misses)
CONTROL queries (answer is in NO card):
  lexical 0/2  semantic 0/2   (the lane doesn't hallucinate a retrieval)
Honest misses (semantic also failed to surface the card): ['s1']
```

Note the unhidden miss (`s1`): the webhook query embeds closer to the charge
cards than the webhook card, so even semantic recall@3 misses it. Left in on
purpose — semantic retrieval is a real improvement, not magic. Requires the
extra (`pip install 'rainman[semantic]'`); without it the script says so.

## Companion: `file_memory_vs_rainman.py` — Rainman vs file-memory (the value-test)

The skeptic's question: *does Rainman's retrieval engine actually beat "just keep
notes in markdown and grep them" — the thing I already do?* This measures it
**deterministically, no LLM**, holding the corpus constant and varying only the
retrieval:

- **file-memory baseline** — a *fair* model of ctrl-F over notes: whole-word
  bag-of-words term match, **stopword-filtered** (so it searches distinctive
  terms like a human would), ranked by match count then recency. No stemming,
  no IDF. This isolates exactly Rainman's two extra mechanisms.
- **Rainman** — `engine.recall()`: stemmed, IDF-weighted, importance/decay/
  associative ranking, top-k.

Both retrieve from one store: 6 answer-bearing cards + a pile of distractors
(some sharing query words on purpose). Queries are `direct` / `morphology` /
`ranking` / `control` (answer in no card). Scored with the repo's own IR metrics.

Result (`python eval/local_demo/file_memory_vs_rainman.py`):

```
query                          class        file-memory   Rainman
authenticating users           morphology          miss       hit   (stemming)
why are sessions slow to load  ranking             miss       hit   (IDF out-ranks a
token expiry in the auth ...   ranking             miss       hit    term-sharing distractor)
... (direct queries: both hit; controls: both correctly surface nothing)

aggregate over 8 answerable queries   recall@5  0.62 -> 1.00   MRR 0.56 -> 0.92   nDCG@5 0.58 -> 0.94
token cost to reach the answer:  file-memory ~458 tok (whole store)  vs  Rainman ~88 tok (top-5)
```

file-memory ties on direct-word queries and wins nothing; Rainman adds the
morphology and rank-under-noise cases grep structurally can't do. The token gap
widens with the store: `--distractors 200` → **42x** less context to surface the
same answer (grep has no ranker, so its reliable mode is "hold everything").

### A bug this test found (and we fixed)

Building this surfaced a real relevance-floor leak. After prior recalls rehearsed
some memories, an **off-domain** control query (`"capital of France"`) surfaced
cards with `keyword=0` but `associative=0.15`. Cause: phase-1 spreading-activation
*anchors* were the top-k by score even when every keyword score was 0 — so pure
recency noise seeded associative boost to its graph neighbours, which then sailed
past the floor. Fix: anchors must be keyword-relevant themselves
(`engine.py`, guarded by `test_relevance_floor_holds_after_rehearsal`). That is
the point of a value-test — it pays for itself by catching this.

### Honest caveats (this companion)

- **Mechanical retrieval only.** It does **not** model an LLM reading a small
  curated `MEMORY.md` and reasoning over it — an LLM is a strong fuzzy matcher,
  so on a *small* store file-memory + a smart reader is competitive. Rainman's
  edge is upstream: **zero tokens** to store/rank, and selection that still works
  when the store is far too big to dump into context (the token-cost column).
- **Synthetic, small-N**, and the corpus/queries are hand-built. Not SWE-bench.

## Honest caveats — what this does NOT show

- **N = 6, synthetic.** The facts were *designed* to be unguessable, so the
  upside is near-maximal by construction. This is closer to an upper bound than
  an expected effect on real work.
- **Not SWE-bench.** No code was written, no test suite was run, no real bug was
  fixed. It measures retrieval + use of memory, not pass-rate lift on hard
  engineering tasks. For that, see `../swebench/` (requires a real agent +
  dataset + compute; ships no fabricated numbers).
- **Somewhat tautological by design.** The answer lives in the injected card, so
  a capable agent that reads it will pass. The interesting, non-trivial part is
  upstream: that `recall()` surfaces the *right* card for the *right* task — run
  `--contexts` to see that it does.
- **Agent-required, not CI.** Producing a fresh run needs an LLM agent, so this
  is excluded from the unit suite. Only the deterministic parts (recall
  contexts, grading a recorded run) run without a model.
