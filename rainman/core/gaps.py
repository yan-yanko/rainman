"""Skill-gap report — where your agents keep getting stuck.

The skills-authoring world converged on a best practice: to know WHICH skill
to write, run the task without one and watch where the agent gets stuck — the
gap is the skill. A Rainman store already contains that gap list, collected
automatically: every failure card is one place an agent got stuck, and every
failure→fix pair is one lesson it had to learn the hard way.

This module turns the store into that backlog: cluster recurring failures
(same union-find over shared stemmed terms/files as consolidate.py), then
rank clusters by how often they recur, how recently, and whether they are
still unresolved. The output reads as a to-do list:

  * recurring + STILL OPEN      -> your top skill/doc/fix candidate
  * recurring + has a known fix -> the agent keeps re-hitting it; recall
                                   covers the recovery, a skill would prevent
                                   the hit entirely

Zero-LLM, pure functions over Memory lists; the engine wires loading.
"""

from collections import Counter, defaultdict

from rainman.core.text import tokenize
from rainman.core.consolidate import _signal_tokens, MIN_SHARED, MIN_OVERLAP

# A failure that happened twice is already a pattern worth seeing.
MIN_CLUSTER = 2

# Recency half-life for ranking: a cluster last seen ~30 days ago carries
# half the urgency of one seen today. Open clusters are doubled — unresolved
# recurring pain outranks pain we at least know how to fix.
DECAY_DAYS = 30
OPEN_BOOST = 2.0


def _is_failure(m):
    return m.category == "failure"


def _experience(m):
    md = m.metadata if isinstance(m.metadata, dict) else {}
    exp = md.get("experience")
    return exp if isinstance(exp, dict) else None


def find_failure_clusters(memories, min_cluster=MIN_CLUSTER,
                          min_shared=MIN_SHARED, min_overlap=MIN_OVERLAP):
    """Group failure memories that recur: pairwise shared stemmed terms/files
    (>= min_shared) plus a Jaccard floor, exactly like consolidation clustering
    — but over failures only, and with a lower membership bar (2 by default:
    the second occurrence is the signal)."""
    failures = [m for m in memories if _is_failure(m)]
    if len(failures) < min_cluster:
        return []

    toks = {m.id: _signal_tokens(m) for m in failures}
    parent = {m.id: m.id for m in failures}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    ids = [m.id for m in failures]
    for i in range(len(ids)):
        a = toks[ids[i]]
        for j in range(i + 1, len(ids)):
            b = toks[ids[j]]
            if not a or not b:
                continue
            shared = a & b
            union_sz = len(a | b)
            jaccard = len(shared) / union_sz if union_sz else 0.0
            if len(shared) >= min_shared and jaccard >= min_overlap:
                union(ids[i], ids[j])

    by_root = defaultdict(list)
    for m in failures:
        by_root[find(m.id)].append(m)
    return [g for g in by_root.values() if len(g) >= min_cluster]


def _cluster_entry(cluster, now):
    """Summarize one cluster of recurring failures into a report row."""
    cluster = sorted(cluster, key=lambda m: m.timestamp)
    latest = cluster[-1]

    open_count = 0
    resolved_count = 0
    known_fix = None
    fix_ts = 0.0
    for m in cluster:
        exp = _experience(m)
        if exp is None:
            open_count += 1  # plain failure with no card: no known fix
            continue
        if exp.get("outcome") == "resolved":
            resolved_count += 1
            if exp.get("fix") and m.timestamp >= fix_ts:
                known_fix, fix_ts = exp["fix"], m.timestamp
        else:
            open_count += 1

    exp = _experience(latest)
    problem = (exp.get("problem") if exp and exp.get("problem")
               else latest.content)
    if problem.startswith("Failure: "):
        problem = problem[len("Failure: "):]

    file_df = Counter()
    for m in cluster:
        for f in m.file_refs:
            file_df[f] += 1
    top_files = [f for f, _ in file_df.most_common(3)]

    tok_df = Counter()
    for m in cluster:
        tok_df.update(set(tokenize(m.content)))
    threshold = max(2, len(cluster) // 2)
    top_terms = [t for t, c in tok_df.most_common() if c >= threshold][:5]

    days_since = max(0.0, (now - latest.timestamp) / 86400)
    decay = 1.0 / (1.0 + days_since / DECAY_DAYS)
    unresolved = open_count > 0 and known_fix is None
    score = len(cluster) * decay * (OPEN_BOOST if unresolved else 1.0)

    return {
        "occurrences": len(cluster),
        "problem": problem,
        "files": top_files,
        "terms": top_terms,
        "first_seen": cluster[0].timestamp,
        "last_seen": latest.timestamp,
        "days_since_last": days_since,
        "open_count": open_count,
        "resolved_count": resolved_count,
        "known_fix": known_fix,
        "unresolved": unresolved,
        "score": score,
        "memory_ids": [m.id for m in cluster],
    }


def gap_report(memories, now, limit=10, min_cluster=MIN_CLUSTER):
    """The report: recurring-failure clusters ranked by
    occurrences x recency-decay x open-boost. Returns at most ``limit`` rows,
    highest score first."""
    clusters = find_failure_clusters(memories, min_cluster=min_cluster)
    rows = [_cluster_entry(c, now) for c in clusters]
    rows.sort(key=lambda r: r["score"], reverse=True)
    return rows[:limit]
