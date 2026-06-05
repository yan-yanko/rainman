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


def keyword_score(entry: Memory, query_words: List[str]) -> float:
    """
    Keyword overlap between query and memory content.
    Boosted by recall count (rehearsal effect from ACT-R).
    Also checks tags and file_refs for matches.
    """
    if not query_words:
        return 0.0

    content_words = set(entry.content.lower().split())
    tag_words = {t.lower() for t in entry.tags}
    ref_words = set()
    for ref in entry.file_refs:
        # "engine/election/predictor.py" -> {"engine", "election", "predictor", "py", "predictor.py"}
        parts = ref.replace("\\", "/").replace("/", " ").replace(".", " ").lower().split()
        ref_words.update(parts)
        # Also add the full filename
        ref_words.add(ref.replace("\\", "/").split("/")[-1].lower())

    all_words = content_words | tag_words | ref_words
    matched = sum(1 for w in query_words if w in all_words)
    overlap = matched / len(query_words)

    # Rehearsal boost (ACT-R: frequently recalled memories strengthen)
    rehearsal = 1 + entry.recall_count * 0.1

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
    rehearsal = 1 + entry.recall_count * 0.15

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


def associative_score(
    entry_id: str,
    all_entries: List[Memory],
    top_ids: List[str],
) -> float:
    """
    Graph-based associative boost.
    Always on (was gated by Big Five openness in CogniTrait).

    Checks if this entry is linked (via linked_ids) to any top-scoring entry.
    """
    # Find the entry
    entry = None
    for e in all_entries:
        if e.id == entry_id:
            entry = e
            break

    if entry is None:
        return 0.0

    # Check forward links: entry -> top result
    linked_to_top = sum(1 for lid in entry.linked_ids if lid in top_ids)

    if linked_to_top == 0:
        # Check reverse links: top result -> entry
        for e in all_entries:
            if e.id in top_ids and entry_id in e.linked_ids:
                linked_to_top += 1

    if linked_to_top == 0:
        return 0.0

    # Cap at 0.6
    return min(0.6, linked_to_top * 0.3)


def compute_score(
    entry: Memory,
    query_words: List[str],
    top_ids: Optional[List[str]] = None,
    all_entries: Optional[List[Memory]] = None,
    now: Optional[float] = None,
) -> Dict[str, float]:
    """
    Full scoring pipeline. Returns component breakdown + total.
    """
    kw = keyword_score(entry, query_words)
    rec = temporal_decay(entry, now=now)
    imp = importance_boost(entry)

    assoc = 0.0
    if top_ids and all_entries:
        assoc = associative_score(entry.id, all_entries, top_ids)

    total = (
        WEIGHTS["keyword"] * kw
        + WEIGHTS["recency"] * rec
        + WEIGHTS["importance"] * imp
        + WEIGHTS["associative"] * assoc
    )

    return {
        "total": total,
        "keyword": kw,
        "recency": rec,
        "importance": imp,
        "associative": assoc,
    }
