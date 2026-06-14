"""
Retrieval Scoring
==================

ACT-R-inspired scoring adapted from CogniTrait.
All personality modulation removed — fixed weights for project memory.

Components:
- keyword:      overlap between query and memory content + rehearsal boost
- recency:      power-law temporal decay (14-day half-life)
- importance:   category-based + keyword boost
- associative:  graph boost from linked memories (always on)

No LLM calls. Pure compute.
"""

import time
from typing import Dict, List, Optional

from rainman.core.models import Memory
from rainman.core import trust
from rainman.core.text import tokenize, tokenize_query, tokenize_refs


# Fixed scoring weights (no personality modulation)
WEIGHTS = {
    "keyword":      0.35,
    "recency":      0.25,
    "importance":   0.20,
    "associative":  0.20,
}

# Category importance baselines
CATEGORY_IMPORTANCE = {
    "failure":    0.90,
    "solution":   0.80,
    "decision":   0.75,
    "pattern":    0.65,
    "convention": 0.60,
    "note":       0.40,
}

# Keywords that boost importance regardless of category
IMPORTANCE_KEYWORDS = {
    "critical", "bug", "fix", "fixed", "breaking", "security",
    "production", "regression", "hotfix", "workaround", "important",
    "never", "always", "must", "required", "danger", "warning",
}


def keyword_score(
    entry: Memory,
    query_words: List[str],
    idf: Optional[Dict[str, float]] = None,
) -> float:
    """
    IDF-weighted lexical overlap between query and memory, over a stemmed,
    punctuation-robust, stopword-filtered token index (content + tags +
    file_refs). Boosted by recall count (rehearsal effect from ACT-R).

    This applies BM25's term-weighting principle: each query term contributes
    its inverse-document-frequency weight, so a rare, meaningful term
    (``saturation``) counts far more than a common one (``bug``). When ``idf``
    is omitted (direct calls / no corpus), every term weighs equally and the
    score degenerates to plain stemmed coverage.

    The result is normalized to ``matched_weight / query_weight`` in [0, 1]
    before the rehearsal multiplier, preserving the weighted-sum contract.
    Stemming collapses morphology (``authenticate``/``authentication``);
    tokenization fixes punctuation asymmetry (``queries.`` vs ``queries``);
    stopword removal stops natural-language queries from being diluted.
    """
    if not query_words:
        return 0.0

    query_terms = set(tokenize_query(query_words))
    if not query_terms:
        return 0.0

    all_words = set(tokenize(entry.content))
    all_words.update(tokenize_query(entry.tags))
    all_words.update(tokenize_refs(entry.file_refs))

    def _w(term: str) -> float:
        # Unseen-in-corpus terms never match a doc, so their weight only sits
        # in the (per-query constant) denominator and never affects ranking.
        return 1.0 if idf is None else idf.get(term, 1.0)

    query_weight = sum(_w(t) for t in query_terms)
    if query_weight == 0:
        return 0.0
    matched_weight = sum(_w(t) for t in query_terms if t in all_words)
    overlap = matched_weight / query_weight

    # Rehearsal boost (ACT-R: frequently recalled memories strengthen)
    # Capped to prevent rich-get-richer: max 2x at 10+ recalls.
    # Denied to ingest-trust memories so a poisoned entry can't ride the
    # rehearsal feedback loop after surfacing once (see core/trust.py).
    if trust.trust_level(entry.source) == trust.INGEST:
        rehearsal = 1.0
    else:
        rehearsal = 1 + min(entry.recall_count, 10) * 0.1

    return overlap * rehearsal


def temporal_decay(entry: Memory, now: Optional[float] = None) -> float:
    """
    ACT-R power-law decay. No personality modulation.

    Half-life: ~14 days for unaccessed memories.
    Rehearsal slows decay (accessed memories persist longer).
    """
    if now is None:
        now = time.time()

    days = max(0, (now - entry.timestamp) / 86400)
    decay_exp = 0.5  # power-law exponent

    # Rehearsal: accessed memories decay slower
    # Capped to prevent unbounded amplification: max 2.5x at 10+ recalls.
    # Denied to ingest-trust memories (see keyword_score / core/trust.py).
    if trust.trust_level(entry.source) == trust.INGEST:
        rehearsal = 1.0
    else:
        rehearsal = 1 + min(entry.recall_count, 10) * 0.15

    return rehearsal / (1 + days ** decay_exp)


def importance_boost(entry: Memory) -> float:
    """
    Category-based importance + keyword boost.
    No personality modulation.
    """
    base = CATEGORY_IMPORTANCE.get(entry.category, 0.40)

    # Keyword boost
    words = set(entry.content.lower().split())
    if words & IMPORTANCE_KEYWORDS:
        base = min(1.0, base + 0.15)

    return base


def build_reverse_link_index(all_entries: List[Memory]) -> Dict[str, set]:
    """
    Build an inverted index: memory_id -> set of IDs that link TO it.
    Avoids O(n) scan per entry during associative scoring.
    """
    index: Dict[str, set] = {}
    for e in all_entries:
        for lid in e.linked_ids:
            if lid not in index:
                index[lid] = set()
            index[lid].add(e.id)
    return index


def associative_score(
    entry_id: str,
    all_entries: List[Memory],
    top_ids: List[str],
    reverse_index: Optional[Dict[str, set]] = None,
    entry: Optional[Memory] = None,
    trust_index: Optional[Dict[str, int]] = None,
    forward_index: Optional[Dict[str, set]] = None,
    max_hops: int = 1,
    decay: float = 0.5,
) -> float:
    """
    Graph-based associative boost via bounded spreading activation (M4).
    Always on (was gated by Big Five openness in CogniTrait).

    Activation spreads from the top-scoring anchors through the link graph:
    a memory directly linked to an anchor (1 hop) is boosted by 0.3 per anchor;
    with ``max_hops >= 2`` a memory linked to *that* memory (2 hops from an
    anchor) gets a ``decay``-attenuated share — so graph-connected knowledge
    surfaces even with no direct link or keyword overlap (HippoRAG-style
    diffusion, arXiv:2405.14831). Capped at 0.6. With ``max_hops == 1`` this is
    exactly the original direct-neighbour boost.

    Trust restriction: when ``trust_index`` (id -> trust rank) is supplied,
    boost is NOT allowed to flow from a *higher-trust* anchor down to a
    lower-trust entry — a poisoned (low-trust) memory can't ride the
    credibility of curated knowledge it auto-linked itself to. Applies at every
    hop. When ``trust_index`` is None, no restriction applies.
    """
    # Use provided entry or fall back to O(n) lookup
    if entry is None:
        for e in all_entries:
            if e.id == entry_id:
                entry = e
                break

    if entry is None:
        return 0.0

    top_set = set(top_ids)

    # An anchor is disqualified if it's strictly more trusted than this entry.
    def _allowed(anchor_id: str) -> bool:
        if trust_index is None:
            return True
        entry_rank = trust_index.get(entry_id, trust.RANK[trust.USER])
        return trust_index.get(anchor_id, trust.RANK[trust.USER]) <= entry_rank

    def _neighbors(mem_id: str, mem_obj: Optional[Memory] = None) -> set:
        """Both-directions neighbours of a node in the link graph."""
        if forward_index is not None:
            fwd = set(forward_index.get(mem_id, ()))
        elif mem_obj is not None:
            fwd = set(mem_obj.linked_ids)
        else:
            fwd = set()
        if reverse_index is not None:
            rev = set(reverse_index.get(mem_id, ()))
        else:
            rev = {e.id for e in all_entries if mem_id in e.linked_ids}
        return fwd | rev

    # 1 hop: anchors directly adjacent to this entry.
    entry_neighbors = _neighbors(entry_id, entry)
    one_hop = {a for a in entry_neighbors if a in top_set and _allowed(a)}
    score = 0.3 * len(one_hop)

    # 2 hops: anchors adjacent to this entry's (non-anchor) neighbours.
    if max_hops >= 2:
        two_hop = set()
        for mid in (entry_neighbors - top_set):
            for a in _neighbors(mid):
                if a in top_set and a not in one_hop and _allowed(a):
                    two_hop.add(a)
        score += 0.3 * decay * len(two_hop)

    return min(0.6, score)


def compute_score(
    entry: Memory,
    query_words: List[str],
    top_ids: Optional[List[str]] = None,
    all_entries: Optional[List[Memory]] = None,
    reverse_index: Optional[Dict[str, set]] = None,
    now: Optional[float] = None,
    trust_index: Optional[Dict[str, int]] = None,
    idf: Optional[Dict[str, float]] = None,
    forward_index: Optional[Dict[str, set]] = None,
    assoc_max_hops: int = 1,
) -> Dict[str, float]:
    """
    Full scoring pipeline. Returns component breakdown + total.

    ``total`` is the weighted sum of the four components scaled by a small
    trust *quality prior* (``trust_prior``). For user-trust memories the prior
    is 1.0, so ``total`` equals the plain weighted sum — the prior only nudges
    auto-learned/ingested memories down as a tiebreaker, never as a security
    boundary (see core/trust.py).
    """
    kw = keyword_score(entry, query_words, idf=idf)
    rec = temporal_decay(entry, now=now)
    imp = importance_boost(entry)

    assoc = 0.0
    if top_ids and all_entries:
        assoc = associative_score(
            entry.id, all_entries, top_ids,
            reverse_index=reverse_index,
            entry=entry,
            trust_index=trust_index,
            forward_index=forward_index,
            max_hops=assoc_max_hops,
        )

    weighted = (
        WEIGHTS["keyword"] * kw
        + WEIGHTS["recency"] * rec
        + WEIGHTS["importance"] * imp
        + WEIGHTS["associative"] * assoc
    )

    prior = trust.quality_prior(entry.source)

    return {
        "total": weighted * prior,
        "keyword": kw,
        "recency": rec,
        "importance": imp,
        "associative": assoc,
        "trust_prior": prior,
    }
