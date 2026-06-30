#!/usr/bin/env python3
"""
Rainman vs file-memory — the value-test
=======================================

The honest question a skeptic asks: *does Rainman's retrieval engine actually
beat the "just keep notes in markdown and grep them" baseline I already use?*
This measures it DETERMINISTICALLY — no LLM, no agent, fully reproducible.

It holds the CORPUS constant and varies only the RETRIEVAL:

  * baseline ("file-memory")  — a fair model of "ctrl-F / grep the markdown":
      bag-of-words term match (whole-word, NO stemming, NO IDF), ranked by
      term-overlap count with recency as the tiebreak. This is the strongest
      *mechanical* version of file notes — exactly the scorer the repo's own IR
      gate says returned 0.000 on morphological queries.
  * treatment ("Rainman")     — engine.recall(): IDF-weighted stemmed keyword +
      temporal decay + importance + associative ranking, top-k.

Both retrieve from the SAME store: a handful of answer-bearing cards plus a
tunable pile of DISTRACTORS (so the right card has to be found among noise, the
way a real store looks after a few weeks). Queries are phrased three ways:

  * direct       — share words with the card (grep should also get these; fair)
  * morphology   — verb/plural/stopword variants (grep misses; stemming gets)
  * ranking      — a distractor shares the query's words, so grep ranks junk
                   first; Rainman's IDF/importance must rank the real card above
  * control      — the answer is in NO card (both must return nothing relevant —
                   proves neither side invents a confident retrieval)

Scored with the repo's own IR metrics (recall@k, MRR, nDCG@k).

    python eval/local_demo/file_memory_vs_rainman.py                 # the measurement
    python eval/local_demo/file_memory_vs_rainman.py --distractors 50  # bury it deeper
    python eval/local_demo/file_memory_vs_rainman.py --contexts      # show what each surfaced
    python eval/local_demo/file_memory_vs_rainman.py --json out.json # machine-readable artifact

SCOPE HONESTY — what this does NOT show. It compares *mechanical* retrieval. It
does NOT model a human/LLM reading a small curated MEMORY.md and reasoning over
it (an LLM is a strong fuzzy matcher). Rainman's claim against THAT is upstream:
zero tokens to store/rank, and selection that holds when the store is too big to
dump into context. The token-cost section below quantifies the second half.
This is synthetic and small-N — NOT the SWE-bench task-success number (../swebench/).
"""

import argparse
import json
import os
import re
import tempfile

from rainman.core.engine import RainmanEngine
from rainman.eval.metrics import ndcg_at_k, reciprocal_rank, recall_at_k, aggregate


# --- the shared corpus -------------------------------------------------------
# label -> (category, content). The label is just our handle on the right hit.
ANSWER_CARDS = {
    "auth":     ("solution",   "Fixed the user authentication flow because JWT tokens were expiring far too early"),
    "dbpool":   ("failure",    "Database connection pool exhaustion under heavy load caused request timeouts"),
    "redis":    ("pattern",    "Use Redis caching for session storage to cut request latency"),
    "ratelimit": ("failure",   "Rate-limiting bug in the API gateway silently dropped valid requests"),
    "nplus1":   ("convention", "Avoid N+1 queries in the ORM layer by enabling eager loading of relations"),
    "webhook":  ("convention", "Webhook delivery retries use exponential backoff with random jitter"),
}

# Distractors that deliberately SHARE words with the queries, so a bag-of-words
# baseline is pulled toward them and has to be out-ranked, not just out-matched.
TERM_SHARING_DISTRACTORS = [
    ("note", "The JWT signing library was bumped to v4 across every service last quarter"),       # shares 'jwt'
    ("note", "Request latency dashboards live in Grafana under the platform folder"),             # shares 'request latency'
    ("note", "Session cookies are set HttpOnly and SameSite=strict in the edge layer"),           # shares 'session'
    ("note", "The pricing rate card is cached in Redis under the rate: prefix with a 600s TTL"),   # shares 'redis rate cache'
    ("note", "A queries-per-second dashboard tracks the ORM read replicas"),                       # shares 'queries orm'
    ("note", "Webhook payload schemas are documented in the partner API portal"),                  # shares 'webhook api'
]

# Filler distractors to inflate the store to a realistic size (no query overlap).
FILLER = [
    "Switched the CI runner image to ubuntu-24.04 for faster cold starts",
    "Feature flags are evaluated through the LaunchToggle SDK at request time",
    "The mobile build signs with the release keystore stored in the vault",
    "Background jobs drain through a priority queue with three worker tiers",
    "Image thumbnails are generated lazily and pinned to the CDN edge",
    "The analytics events schema is versioned and validated at ingest",
    "Localization strings are pulled from the translation service nightly",
    "The search index rebuilds incrementally off the change-data-capture stream",
]

# (query, expected_label, class). Controls have expected_label=None.
QUERIES = [
    ("Redis caching for sessions",                 "redis",     "direct"),
    ("webhook exponential backoff",                "webhook",   "direct"),
    ("authenticating users",                       "auth",      "morphology"),
    ("how do I fix the database timeouts",         "dbpool",    "morphology"),
    ("rate limiting bugs",                         "ratelimit", "morphology"),
    ("running n+1 queries in the orm",             "nplus1",    "morphology"),
    ("why are sessions slow to load",              "redis",     "ranking"),     # distractors share 'session'
    ("token expiry in the auth service",           "auth",      "ranking"),     # JWT-bump distractor shares 'jwt/auth'
    ("what is the capital of France",              None,        "control"),     # off-domain: answer in no card
    ("a good recipe for sourdough bread",          None,        "control"),
]

# Function words a real person wouldn't ctrl-F for. Stripping them makes the
# grep baseline FAIRER (it searches the distinctive terms, like a human would),
# so the comparison isolates exactly Rainman's two extra mechanisms — stemming
# and IDF/importance ranking — rather than punishing grep for stopword noise.
_STOPWORDS = {
    "the", "a", "an", "is", "are", "do", "does", "how", "why", "what", "i", "to",
    "in", "on", "for", "of", "and", "my", "me", "you", "we", "it", "this", "that",
    "with", "as", "at", "be", "by", "or", "so", "good", "am",
}


def seed_engine(n_distractors: int):
    """Seed a real engine with answer cards + distractors. Returns
    (engine, label->id, [(id, content, recency_index)]) — the last list lets the
    grep baseline retrieve over the SAME ids the engine assigned."""
    tmp = tempfile.mkdtemp(prefix="value_test_")
    e = RainmanEngine(project_dir=os.path.join(tmp, "p"), global_dir=os.path.join(tmp, "g"))
    e.store.init_project(os.path.join(tmp, "p"))
    e.store.init_global()

    label_by_id, corpus = {}, []
    order = 0

    def _add(category, content, label=None):
        nonlocal order
        m = e.add(content, category=category)
        if label:
            label_by_id[m.id] = label
        corpus.append((m.id, content, order))
        order += 1

    for label, (cat, content) in ANSWER_CARDS.items():
        _add(cat, content, label)
    for cat, content in TERM_SHARING_DISTRACTORS:
        _add(cat, content)
    # Pad to the requested distractor count by cycling the filler pool.
    for i in range(n_distractors):
        _add("note", FILLER[i % len(FILLER)] + f" (#{i})")

    return e, label_by_id, corpus


# --- the two retrievers ------------------------------------------------------
_WORD = re.compile(r"\w+")


def grep_recall(corpus, query: str, k: int):
    """Baseline 'file-memory' retrieval: whole-word bag-of-words term match, NO
    stemming / NO IDF, ranked by (#distinct query terms matched, then recency).
    Models skimming markdown notes with ctrl-F. Returns ordered ids."""
    terms = {t for t in _WORD.findall(query.lower()) if len(t) > 2 and t not in _STOPWORDS}
    scored = []
    for mid, content, recency in corpus:
        text = content.lower()
        hits = sum(1 for t in terms if re.search(rf"\b{re.escape(t)}\b", text))
        if hits:
            scored.append((hits, recency, mid))
    scored.sort(key=lambda x: (x[0], x[1]), reverse=True)  # more matches, then newer
    return [mid for _, _, mid in scored[:k]]


def rainman_recall(engine, query: str, k: int):
    return [r.memory.id for r in engine.recall(query, limit=k)]


# --- measurement -------------------------------------------------------------
def run(n_distractors: int, k: int = 5):
    engine, label_by_id, corpus = seed_engine(n_distractors)
    id_by_label = {v: k_ for k_, v in label_by_id.items()}

    rows, grep_rr, rain_rr, grep_rec, rain_rec, grep_nd, rain_nd = [], [], [], [], [], [], []
    for query, label, qclass in QUERIES:
        rel = [id_by_label[label]] if label else []
        g_ids = grep_recall(corpus, query, k)
        r_ids = rainman_recall(engine, query, k)

        if qclass == "control":
            # No relevant id exists; "hit" = surfaced nothing -> good.
            g_hit = len(g_ids) == 0
            r_hit = len(r_ids) == 0
        else:
            g_hit = reciprocal_rank(g_ids, rel) > 0
            r_hit = reciprocal_rank(r_ids, rel) > 0
            grep_rr.append(reciprocal_rank(g_ids, rel))
            rain_rr.append(reciprocal_rank(r_ids, rel))
            grep_rec.append(recall_at_k(g_ids, rel, k))
            rain_rec.append(recall_at_k(r_ids, rel, k))
            grep_nd.append(ndcg_at_k(g_ids, rel, k))
            rain_nd.append(ndcg_at_k(r_ids, rel, k))

        rows.append({
            "query": query, "class": qclass, "expected": label,
            "grep_hit": g_hit, "rainman_hit": r_hit,
            "grep_ids": g_ids, "rainman_ids": r_ids,
        })

    report = {
        "k": k,
        "n_distractors": n_distractors,
        "corpus_size": len(corpus),
        "scored_queries": len(grep_rr),
        "grep":    {"recall_at_k": aggregate(grep_rec), "mrr": aggregate(grep_rr),
                    "ndcg_at_k": aggregate(grep_nd)},
        "rainman": {"recall_at_k": aggregate(rain_rec), "mrr": aggregate(rain_rr),
                    "ndcg_at_k": aggregate(rain_nd)},
        "rows": rows,
        "token_cost": _token_cost(engine, corpus, k),
    }
    return report


def _approx_tokens(text: str) -> int:
    return max(1, len(text) // 4)  # ~4 chars/token; a label, not a real tokenizer (zero-dep)


def _token_cost(engine, corpus, k: int):
    """The efficiency half of the claim. Without a ranker, file-memory's reliable
    mode is to hold the whole store in context (you can't know which note matters
    until you read it). Rainman injects only top-k. Cost ratio grows with the
    store; Rainman's stays fixed at k."""
    whole = sum(_approx_tokens(c) for _, c, _ in corpus)
    per_card = whole / len(corpus)
    topk = int(round(per_card * k))
    return {"whole_corpus_tokens": whole, "rainman_topk_tokens": topk,
            "ratio": round(whole / max(1, topk), 1)}


# --- presentation ------------------------------------------------------------
def _print(report):
    print(f"corpus = {len(ANSWER_CARDS)} answer cards + {report['n_distractors']} distractors "
          f"= {report['corpus_size']} memories   (recall@{report['k']}, deterministic, no LLM)\n")
    print(f"{'query':46} {'class':11} {'file-memory':>12} {'Rainman':>9}")
    print("-" * 82)
    for r in report["rows"]:
        print(f"{r['query'][:46]:46} {r['class']:11} "
              f"{('hit' if r['grep_hit'] else 'miss'):>12} "
              f"{('hit' if r['rainman_hit'] else 'miss'):>9}")

    g, rn = report["grep"], report["rainman"]
    print(f"\n{'':46} {'class':11} {'file-memory':>12} {'Rainman':>9}")
    print(f"{'aggregate over ' + str(report['scored_queries']) + ' answerable queries':57} "
          f"recall@{report['k']}   {g['recall_at_k']:.2f}  ->  {rn['recall_at_k']:.2f}")
    print(f"{'':57} MRR        {g['mrr']:.2f}  ->  {rn['mrr']:.2f}")
    print(f"{'':57} nDCG@{report['k']}     {g['ndcg_at_k']:.2f}  ->  {rn['ndcg_at_k']:.2f}")

    controls = [r for r in report["rows"] if r["class"] == "control"]
    clean = all(r["grep_hit"] and r["rainman_hit"] for r in controls)  # hit==returned-nothing
    print(f"\ncontrol queries (answer in NO card): "
          f"{'both correctly surfaced nothing' if clean else 'WARNING: a side invented a retrieval'}")

    tc = report["token_cost"]
    print("\ntoken cost to make the answer reachable at this store size:")
    print(f"  file-memory (hold the whole store): ~{tc['whole_corpus_tokens']} tokens")
    print(f"  Rainman (inject top-{report['k']} only):       ~{tc['rainman_topk_tokens']} tokens "
          f"  ({tc['ratio']}x less, and it stays flat as the store grows)")
    print("\n(Synthetic, small-N, mechanical retrieval — NOT a SWE-bench task-success number.)")


def _print_contexts(report):
    for r in report["rows"]:
        print(f"### [{r['class']}] {r['query']}  (expect: {r['expected']})")
        print(f"  file-memory top-ids: {r['grep_ids']}")
        print(f"  Rainman     top-ids: {r['rainman_ids']}\n")


def main(argv=None):
    from rainman.core.encoding import ensure_utf8_io
    ensure_utf8_io()  # dogfood the UTF-8 fix so the table renders on Windows too

    ap = argparse.ArgumentParser(description="Rainman vs file-memory value-test")
    ap.add_argument("--distractors", type=int, default=14,
                    help="extra noise memories in the store (default 14)")
    ap.add_argument("-k", type=int, default=5, help="top-k retrieved (default 5)")
    ap.add_argument("--contexts", action="store_true", help="show the ids each side surfaced")
    ap.add_argument("--json", metavar="PATH", help="write the full report as JSON")
    a = ap.parse_args(argv)

    report = run(a.distractors, k=a.k)
    if a.json:
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)
        print(f"wrote {a.json}")
    if a.contexts:
        _print_contexts(report)
    else:
        _print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
