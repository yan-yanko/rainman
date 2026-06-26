# What changed — and why it matters

A founder-facing summary of the cycle that turned Rainman from "a clean memory
feature" into a tool with a defensible position. Plain language, honest about
what's proven versus pending.

## The one-line version

**Rainman is the only developer-memory layer that turns real dev outcomes into
deduplicated, contradiction-aware, causally-typed experience — fully on your
machine, zero tokens, zero data egress — and surfaces the right one at the
moment you hit the problem again.**

## The shift

The old engine was a keyword scorer — replaceable in a weekend, and it silently
returned *nothing* when you described a problem in different words than you'd
written it. Worse, the hook meant to *capture* knowledge was reading the wrong
field, so the highest-value signal (what failed, what fixed it) was never even
recorded.

We rebuilt around the part that's actually hard to copy: **the write side.**

The flywheel now:

1. **Capture** — the hook records real failures and fixes from how you actually
   code (this was silently broken; it's fixed and tested).
2. **Structure** — a failing test run and the later passing run on the same
   files are paired into one typed `problem → fix` experience card.
3. **Curate** — near-duplicates merge instead of piling up; superseded
   decisions ("we no longer use X") are retired automatically.
4. **Surface** — when you next hit that error or open that file, the right card
   is recalled — conditioned on your current task, not just your wording, and
   reachable across synonyms via an optional on-device embedding lane.
5. **Prove** — retrieval quality is now measured by a CI gate, and a turnkey
   harness measures memory's effect on agent task-success.

All of it is local, zero-LLM for storage/ranking, and zero-dependency in the
core. (The semantic lane is the one opt-in extra; it's a small CPU model that
still never leaves your machine.)

## Why this is defensible

The scoring math was never the moat — embeddings are a `pip install`. The moat
is **(a)** the privileged, zero-egress channel that *harvests* real
problem→attempt→outcome trajectories from production developer behavior for
free, **(b)** doing the genuinely hard curation/consolidation entirely
on-device, and **(c)** a measured result.

The competitors (Mem0, Letta, Zep, the IDE built-ins) are all cloud + LLM +
embeddings. They **cannot** match "nothing leaves your machine, zero token cost,
runs air-gapped" without abandoning their business model. That's the wedge.

## The buyer

The air-gapped / regulated / IP-sensitive engineering org — defense, healthcare,
finance, frontier labs guarding their own code — where *"no source-derived
context may leave our infrastructure"* is a hard procurement gate, not a
preference. For them, a memory layer that's verifiably local is the difference
between "can deploy" and "blocked by security review."

## What's proven (reproducible, today)

- **Retrieval quality gate** — paraphrased queries that used to score 0.000 now
  resolve: recall@5 = 1.00, MRR = 1.00 on the in-repo gold set
  (`pytest tests/test_retrieval_quality.py`).
- **Memory changes agent answers** — fresh agents on an invented codebase:
  **0/6 → 6/6** with memory injected (`eval/local_demo/quillpay_demo.py`).
- **The semantic lane works on a real model** — with `potion-base-8M`, synonym
  queries that share no words with their card go from **2/6 → 5/6**
  answer-retrieval (`eval/local_demo/semantic_lift.py`), with one honest
  unhidden miss. Verified end-to-end by live tests (`tests/test_semantic_live.py`).
- **268 tests** in the zero-dependency CI (271 with the semantic extra
  installed), `ruff` clean.

## What's pending (honest)

The **headline number — memory-on vs memory-off task-success on SWE-bench
Verified** — is not produced here, because it requires a real coding agent run
over the dataset on real compute (per-repo test environments), which is outside
a single session. The harness is **turnkey** (`eval/swebench/` — bring tasks +
your agent, no script editing); producing the number is the next concrete step.
We ship no fabricated results anywhere.

## Where to look

- `CLAUDE.md` — architecture + the scoring/recall/curation design
- `eval/local_demo/` — the reproducible mechanism + semantic-lane demos
- `eval/swebench/` — the turnkey task-success harness (+ `example_*`)
- the memory of the strategy lives in the project's own Rainman store
