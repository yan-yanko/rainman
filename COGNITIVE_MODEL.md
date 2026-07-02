# Rainman and human memory — a mechanism-by-mechanism map

Rainman's retrieval engine wasn't designed by reading cognitive science — but
when we later mapped it against the literature, it turned out to already
implement the single best-specified mechanism (spreading activation) almost line
for line. So we built the rest.

This document maps each **well-established, reliable** mechanism of human memory
to how Rainman implements it — with the paper *and* the file. The point isn't to
claim Rainman "thinks like a brain." It's that these mechanisms are good,
battle-tested *algorithms*, and a local, zero-LLM store can implement them
faithfully.

**The thesis in one line:** Rainman borrows the *reliable* mechanisms of human
memory and deliberately omits the one that makes human memory *unreliable* —
reconstruction, i.e. false memories. That omission is the only part you'd need
an LLM for, so skipping it is both the zero-LLM boundary and the trust guarantee.

---

## The map

### Retrieval & activation

| Human memory | Rainman | Where |
|---|---|---|
| **Spreading activation** — activation spreads from a cued node as a *decreasing gradient* attenuated by link strength, *summates* across multiple cues, and fires only past a *threshold* (Collins & Loftus 1975) | 2-hop spreading activation over the associative link graph: two-phase re-scoring with top-K anchors, decayed diffusion, capped associative boost, and a relevance floor | `core/scoring.py`, `core/engine.py` (recall) |
| **ACT-R base-level activation** — how retrievable a memory is rises with *recency* and *frequency* of use (Anderson & Schooler 1991) | Recency = power-law decay (14-day half-life); frequency = `recall_count` rehearsal boost (capped to prevent rich-get-richer) | `core/scoring.py` |
| **Cue- / context-dependent retrieval** — retrieval depends on cues present at encoding (encoding-specificity; Tulving & Thomson 1973) | Task-state conditioning: a memory whose stored `file_refs` / error signature matches the *current* file or error is boosted and clears the relevance floor (M2) | `core/engine.py` |

### Encoding & typing

| Human memory | Rainman | Where |
|---|---|---|
| **Declarative-memory taxonomy** — episodic (context-tagged events), semantic (context-free facts), procedural (skills/rules) (Squire 2004; Tulving 1972–1985) | `Memory.memory_type`, *derived* (no stored field): episodic = experience card or failure/solution anchored to files; procedural = convention/pattern; semantic = context-free fact, plus any consolidated generalization | `core/models.py` |
| **Levels-of-processing** — retention tracks the *type* of processing, semantic > shallow (Craik & Lockhart 1972) | Write-side salience curation weights signal-rich content higher when deciding what's worth storing (a rough proxy) | `core/salience.py` |

### Forgetting & decay

| Human memory | Rainman | Where |
|---|---|---|
| **Ebbinghaus forgetting curve** — retention decays steep-then-flat, `Q(t)=1.84/((log t)^1.25+1.84)` (Ebbinghaus 1885; Murre & Dros 2015) | ACT-R-style power-law temporal decay in the recency term (not linear) | `core/scoring.py` |
| **Functional / adaptive forgetting** — un-rehearsed, low-value traces fade; forgetting is useful, not just failure | The "sleep" pass drops old, un-recalled, low-importance, orphan, *auto-learned* memories — never user knowledge, links, generalizations, or experience cards | `core/consolidate.py` (`forgettable`) |

### Consolidation & updating

| Human memory | Rainman | Where |
|---|---|---|
| **Extract common elements across events** — declarative memory captures what's unique to one event; the complementary system *gradually extracts the common elements across many events* (Squire 2004) | Episodic→semantic consolidation: recurring episodic memories are clustered by similarity and abstracted into a semantic *generalization* card, linked back to the source events | `core/consolidate.py`, `engine.consolidate()` |
| **Offline consolidation** — labile traces are reorganized into stable ones offline (Stickgold & Walker 2007) | The consolidation + forgetting pass runs as a "sleep" step — on demand (`rainman consolidate`) or at session end (policy-gated) | `engine.consolidate()`, `integration/core.py` (`maybe_sleep`) |
| **Reconsolidation** — retrieving a memory returns it to a *labile, updatable* state; new info integrates into the existing trace (Nader, Schafe & LeDoux 2000; Nader 2015) | `engine.reconsolidate()` integrates new info into a memory in place, keeping prior versions; and a re-observation of a memory *recalled within a labile window* is integrated rather than duplicated. **No prediction-error gate** — the "surprise required" precondition did not survive verification | `core/engine.py` |

### Working memory

| Human memory | Rainman | Where |
|---|---|---|
| **Capacity-limited buffer** — a small (~7±2) store of what's *currently in mind*, distinct from long-term memory (Miller 1956; Baddeley) | A TTL'd, LRU working-memory buffer of the memories surfaced this session; recall touches it, and it's re-injected at session start so focus carries over | `core/working.py`, `integration/core.py` |

---

## The one deliberate omission

| Human memory | Rainman |
|---|---|
| **Reconstructive memory** — recall rebuilds the gist from schemas rather than replaying a recording, which produces *false memories*, source-monitoring errors, and schema-driven distortion (Bartlett; Roediger; Rubin 2021) | **Not implemented.** Rainman stores and surfaces content *verbatim* — it never rewords, summarizes, or reconstructs. A consolidated generalization lists the *common terms* that recurred; it does not fabricate prose. |

This is the crux. Reconstruction is the one memory operation you'd need an LLM
for — and it's precisely the one that lies. By staying keyword-based, Rainman
gets the trustworthy mechanisms and skips the hallucinating one. The zero-LLM
constraint isn't a limitation here; it's what keeps the memory honest.

---

## What this does and doesn't claim

- **These are algorithmic analogies, not claims about consciousness or
  neuroscience.** Rainman implements the *computational* form of each mechanism
  (activation dynamics, decay curves, clustering), not its biology.
- **The implementations are keyword-based and math-based** — stemmed IDF-weighted
  matching, power-law decay, graph diffusion, similarity clustering. No
  embeddings, no model, zero LLM calls.
- **Citations are to the canonical literature.** Several (the ACT-R equation,
  working-memory capacity, reconstructive-memory failure modes) are textbook and
  are cited as such; the load-bearing mechanisms for retrieval (spreading
  activation), decay (Ebbinghaus), taxonomy/consolidation (Squire), and
  reconsolidation (Nader) trace to primary sources.
- **"Human-like" is a design lens, not a benchmark claim.** For what Rainman's
  memory actually buys you empirically, see the honest evals in `eval/` — memory
  beats *no* memory on unguessable project facts, and against plain grep'd notes
  the win is retrieval quality / automation / scale, not a proven task-success
  lift.

---

## References

- Anderson, J. R., & Schooler, L. J. (1991). *Reflections of the environment in
  memory.* Psychological Science, 2(6). (ACT-R base-level activation.)
- Collins, A. M., & Loftus, E. F. (1975). *A spreading-activation theory of
  semantic processing.* Psychological Review, 82(6), 407–428.
- Craik, F. I. M., & Lockhart, R. S. (1972). *Levels of processing.* Journal of
  Verbal Learning and Verbal Behavior, 11(6). (Note: the strong "depth causes
  persistence" and "maintenance rehearsal is worthless" extensions are contested
  and did not survive our verification — repetition does help.)
- Ebbinghaus, H. (1885). *Über das Gedächtnis.* Curve replicated and fitted by
  Murre, J. M. J., & Dros, J. (2015), PLOS ONE.
- Miller, G. A. (1956). *The magical number seven, plus or minus two.*
  Psychological Review, 63(2). (Working-memory span; see also Baddeley's model.)
- Nader, K., Schafe, G. E., & LeDoux, J. E. (2000). *Fear memories require
  protein synthesis in the amygdala for reconsolidation after retrieval.* Nature,
  406. See also Nader, K. (2015), Cold Spring Harbor Perspectives in Biology.
- Squire, L. R. (2004). *Memory systems of the brain.* Neurobiology of Learning
  and Memory, 82(3). (Declarative taxonomy; "extract common elements" principle.)
- Stickgold, R., & Walker, M. P. (2007). *Sleep-dependent memory consolidation
  and reconsolidation.* Sleep Medicine, 8(4).
- Tulving, E. (1972, 1983, 1985). Episodic vs semantic memory. See also Rubin, D.
  C. (2021), Memory & Cognition, for the dimensional refinement.
