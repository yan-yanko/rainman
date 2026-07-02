"""Consolidation & functional forgetting — the offline "sleep" pass.

Human declarative memory does two things a flat store doesn't, and both are
well established (see the memory research map):

  * It EXTRACTS THE COMMON ELEMENTS across many separate events — Squire's
    (2004) operating principle that turns repeated episodes into general
    knowledge (episodic -> semantic).
  * It FORGETS adaptively — un-rehearsed, low-value traces fade (the Ebbinghaus
    curve), which is functional, not failure.

This module is the zero-LLM analog:

  find_episodic_clusters  group recurring EPISODIC memories that share
                          distinctive terms / files
  generalize              turn a cluster into a SEMANTIC generalization
                          (keyword-based — we surface WHAT recurred; a zero-LLM
                          store never rewords, which is exactly the human
                          failure mode it thereby avoids: reconstructed / false
                          memory)
  forgettable             pick old, un-recalled, low-value, ORPHAN, auto-learned
                          memories to drop (never user knowledge, never linked,
                          never generalizations, never experience cards)

Pure functions over a list of Memory; the engine wires persistence + audit.
"""

from collections import Counter, defaultdict

from rainman.core.text import tokenize, tokenize_refs

# Clustering
MIN_CLUSTER = 3    # events needed before something counts as a "recurring" pattern
MIN_SHARED = 2     # shared terms/files needed to link two events
MIN_OVERLAP = 0.25  # Jaccard overlap needed too (guards generic single-word links)

# Functional forgetting — conservative by construction.
FORGET_MIN_AGE_DAYS = 30
FORGET_MAX_IMPORTANCE = 0.4


def _signal_tokens(m):
    """Distinctive signal of a memory: stemmed content tokens + file basenames."""
    return set(tokenize(m.content)) | set(tokenize_refs(m.file_refs))


def _is_consolidatable_episodic(m):
    md = m.metadata if isinstance(m.metadata, dict) else {}
    return (m.memory_type == "episodic"
            and not md.get("consolidated_from")
            and not md.get("consolidated_into"))


def find_episodic_clusters(memories, min_cluster=MIN_CLUSTER,
                           min_shared=MIN_SHARED, min_overlap=MIN_OVERLAP):
    """Group episodic memories that RECUR — i.e. are SIMILAR to each other:
    they share >= min_shared (stopword-filtered) terms/files AND clear a Jaccard
    overlap floor (so two events sharing one generic word don't merge). Returns
    clusters (lists of Memory) with >= min_cluster members. Already-consolidated
    events are excluded, so the pass is idempotent.

    Note: similarity is measured pairwise, NOT against corpus frequency — in a
    store of mostly-similar events every shared token looks "common", so a
    global distinctiveness cut would wrongly erase the very signal that links
    a recurring pattern together."""
    episodics = [m for m in memories if _is_consolidatable_episodic(m)]
    if len(episodics) < min_cluster:
        return []

    toks = {m.id: _signal_tokens(m) for m in episodics}
    parent = {m.id: m.id for m in episodics}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    ids = [m.id for m in episodics]
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
    for m in episodics:
        by_root[find(m.id)].append(m)
    return [g for g in by_root.values() if len(g) >= min_cluster]


def generalize(cluster):
    """Extract the common elements of a cluster into a semantic generalization.
    Returns (content, category, file_refs, top_terms). Keyword-based on purpose:
    a zero-LLM store surfaces what recurred, it does not fabricate prose."""
    n = len(cluster)
    tok_df = Counter()
    for m in cluster:
        tok_df.update(set(tokenize(m.content)))
    threshold = max(2, n // 2)
    top_terms = [t for t, c in tok_df.most_common() if c >= threshold][:6]

    file_df = Counter()
    for m in cluster:
        for f in m.file_refs:
            file_df[f] += 1
    top_files = [f for f, _ in file_df.most_common(5)]

    terms_str = ", ".join(top_terms) if top_terms else "(shared context)"
    content = f"Recurring pattern across {n} related events — common terms: {terms_str}."
    if top_files:
        content += f" Files: {', '.join(top_files)}."
    return content, "pattern", top_files, top_terms


def forgettable(memories, now, min_age_days=FORGET_MIN_AGE_DAYS,
                max_importance=FORGET_MAX_IMPORTANCE):
    """Ids of memories safe to functionally forget: OLD, NEVER recalled, LOW
    importance, ORPHAN (no links in or out), and AUTO-LEARNED. Never touches
    user knowledge, linked memories, consolidated generalizations, or experience
    cards. Conservative by design — forgets the clear noise, nothing load-bearing."""
    linked = set()
    for m in memories:
        linked.update(m.linked_ids)

    drop = []
    for m in memories:
        md = m.metadata if isinstance(m.metadata, dict) else {}
        if (now - m.timestamp) / 86400 < min_age_days:
            continue
        if m.recall_count > 0:
            continue
        if m.importance >= max_importance:
            continue
        if m.trust == "user":          # never forget explicit human knowledge
            continue
        if md.get("consolidated"):      # never forget a generalization
            continue
        if md.get("experience"):        # never forget a typed-causal card
            continue
        if m.linked_ids or m.id in linked:  # orphan only
            continue
        drop.append(m.id)
    return drop
