"""
Retrieval-quality gate (the IR benchmark)
==========================================

A deterministic, stdlib-only benchmark of *recall quality*, not just "the code
runs." It encodes a small gold set of developer memories and queries — many of
them phrased the way a developer actually asks weeks later (morphological
variants, punctuation differences, natural-language questions full of
stopwords) — and asserts recall@5 / MRR thresholds.

Why this exists: the prior exact-token bag-of-words scorer returned 0.000 on
every one of these queries (a memory about "authentication" was invisible to a
query for "authenticating"). This file is the regression gate that proves the
stemmed, IDF-weighted scorer fixes that, and the harness future retrieval work
(local embeddings, graph diffusion) is measured against.

Scope honesty: lexical retrieval fixes morphology / punctuation / stopwords. It
does NOT fix synonyms or abbreviations (``auth`` vs ``authentication``); those
are the job of the optional semantic lane and are intentionally NOT asserted
here.
"""

import os

import pytest

from rainman.core.engine import RainmanEngine
from rainman.core.scoring import keyword_score
from rainman.core.models import Memory


# label -> (content, category). The label is just our handle on the expected hit.
GOLD_MEMORIES = {
    "auth":     ("Fixed the user authentication flow because JWT tokens were expiring far too early", "solution"),
    "dbpool":   ("Database connection pool exhaustion under heavy load caused request timeouts", "failure"),
    "redis":    ("Use Redis caching for session storage to cut request latency", "pattern"),
    "grpc":     ("Migrated the billing service from REST endpoints to gRPC for throughput", "decision"),
    "ratelimit": ("Rate-limiting bug in the API gateway silently dropped valid requests", "failure"),
    "nplus1":   ("Avoid N+1 queries in the ORM layer by enabling eager loading of relations", "convention"),
    "deploy":   ("The deployment pipeline runs schema migrations automatically on every release", "note"),
    "darkmode": ("CSS dark-mode toggle had a flash-of-unstyled-content rendering issue", "solution"),
    "logging":  ("Configured structured logging with correlation identifiers across services", "pattern"),
    "webhook":  ("Webhook delivery retries use exponential backoff with random jitter", "convention"),
}

# (query, expected label). Each query is phrased UNLIKE the stored wording on
# purpose — these are exactly the cases the old scorer scored 0.000 on.
GOLD_QUERIES = [
    ("authenticating users",                       "auth"),       # morphology: authenticating -> authent
    ("how do I fix the database timeouts",         "dbpool"),     # stopwords + plural -> singular
    ("session caching strategy",                   "redis"),      # caching -> cach
    ("rate limiting bugs",                         "ratelimit"),  # punctuation + plural
    ("n+1 queries in the orm",                     "nplus1"),     # punctuation: N+1, queries -> queri
    ("running migrations on deploy",               "deploy"),     # migrations -> migrat, running -> run
    ("exponential backoff for webhooks",           "webhook"),    # plural + reordering
]


@pytest.fixture
def loaded_engine(tmp_path):
    project = str(tmp_path / "project")
    global_dir = str(tmp_path / "global")
    os.makedirs(project)
    os.makedirs(global_dir)
    e = RainmanEngine(project_dir=project, global_dir=global_dir)
    e.store.init_project(project)
    e.store.init_global()

    labels_by_id = {}
    for label, (content, category) in GOLD_MEMORIES.items():
        m = e.add(content, category=category)
        labels_by_id[m.id] = label
    return e, labels_by_id


@pytest.mark.unit
class TestRetrievalQuality:

    def test_recall_at_5_and_mrr(self, loaded_engine):
        engine, labels_by_id = loaded_engine

        hits_at_5 = 0
        reciprocal_ranks = []
        misses = []
        for query, expected in GOLD_QUERIES:
            results = engine.recall(query, limit=5)
            ranked = [labels_by_id.get(r.memory.id) for r in results]
            if expected in ranked:
                hits_at_5 += 1
                reciprocal_ranks.append(1.0 / (ranked.index(expected) + 1))
            else:
                reciprocal_ranks.append(0.0)
                misses.append((query, expected, ranked))

        n = len(GOLD_QUERIES)
        recall_at_5 = hits_at_5 / n
        mrr = sum(reciprocal_ranks) / n

        # Every gold query must surface its target in the top 5 — the old
        # bag-of-words scorer would have scored these 0.000 and missed entirely.
        assert recall_at_5 == 1.0, f"recall@5={recall_at_5:.2f}, misses={misses}"
        # And the target should usually be rank 1 — IDF weighting + category
        # importance should put the on-topic memory first.
        assert mrr >= 0.80, f"MRR={mrr:.3f} below gate (per-query rr={reciprocal_ranks})"

    def test_relevance_floor_returns_nothing_on_irrelevant_query(self, loaded_engine):
        """A query that matches no memory must return [] — not the most recent
        memory surfaced on recency alone. Confident noise is worse than nothing."""
        engine, _ = loaded_engine
        results = engine.recall("quantum blockchain tulip mania horoscope")
        assert results == []

    def test_irrelevant_recent_memory_not_injected(self, loaded_engine):
        """Reproduces the documented failure: a fresh irrelevant note must not
        outrank / displace a relevant older memory for an on-topic query."""
        engine, labels_by_id = loaded_engine
        # Add a very recent but totally unrelated note.
        engine.add("renamed a variable in the project readme for clarity", category="note")
        results = engine.recall("database connection pool timeout", limit=3)
        labels = [labels_by_id.get(r.memory.id) for r in results]
        assert "dbpool" in labels
        assert results[0].memory.id != "" and labels[0] == "dbpool"

    def test_relevance_floor_holds_after_rehearsal(self, loaded_engine):
        """Regression (found by eval/local_demo/file_memory_vs_rainman.py): the
        floor must hold even after other recalls have rehearsed some memories.
        Prior recalls change which memories rank highest in phase 1; if those
        recency-ranked-but-irrelevant memories are allowed to anchor spreading
        activation, their graph neighbours get a non-zero associative score and
        leak past the floor on a genuinely off-domain query. Anchors must be
        keyword-relevant themselves."""
        engine, _ = loaded_engine
        # Rehearse a spread of memories (as a real session would).
        for q in ("authenticating users", "session caching", "rate limiting bugs",
                  "n+1 queries in the orm", "exponential backoff webhooks"):
            engine.recall(q, limit=5)
        # Now a query unrelated to anything stored must STILL return nothing.
        assert engine.recall("quantum blockchain tulip mania horoscope") == []
        assert engine.recall("what is the capital of France") == []

    def test_morphology_match_is_nonzero(self):
        """Direct guard on the core win: a query morphologically related to the
        stored content scores > 0. The old exact-token scorer returned 0.0."""
        m = Memory(
            id="rm_morph",
            content="Fixed the user authentication flow",
            timestamp=0.0,
            importance=0.5,
            category="solution",
        )
        assert keyword_score(m, ["authenticating"]) > 0.0
        assert keyword_score(m, ["authentication"]) > 0.0
        # Punctuation asymmetry no longer breaks matching.
        q = Memory(id="rm_q", content="avoid N+1 queries.", timestamp=0.0, importance=0.5, category="note")
        assert keyword_score(q, ["queries"]) > 0.0
        assert keyword_score(q, ["query"]) > 0.0  # morphology: query/queries -> queri
