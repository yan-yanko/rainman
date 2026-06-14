"""
Information-retrieval metrics (pure stdlib)
===========================================

Standard ranked-retrieval metrics. ``retrieved`` is an ordered list of result
ids (best first); ``relevant`` is the set/iterable of ids that count as correct.
"""

import math
from typing import Iterable, List, Sequence, Tuple


def recall_at_k(retrieved: Sequence[str], relevant: Iterable[str], k: int) -> float:
    """Fraction of the relevant items that appear in the top-k results."""
    rel = set(relevant)
    if not rel:
        return 0.0
    topk = list(retrieved)[:k]
    hits = sum(1 for r in topk if r in rel)
    return hits / len(rel)


def precision_at_k(retrieved: Sequence[str], relevant: Iterable[str], k: int) -> float:
    """Fraction of the top-k results that are relevant."""
    if k <= 0:
        return 0.0
    rel = set(relevant)
    topk = list(retrieved)[:k]
    hits = sum(1 for r in topk if r in rel)
    return hits / k


def reciprocal_rank(retrieved: Sequence[str], relevant: Iterable[str]) -> float:
    """1 / rank of the first relevant result (0 if none retrieved)."""
    rel = set(relevant)
    for i, r in enumerate(retrieved):
        if r in rel:
            return 1.0 / (i + 1)
    return 0.0


def mean_reciprocal_rank(cases: Iterable[Tuple[Sequence[str], Iterable[str]]]) -> float:
    """Mean reciprocal rank over (retrieved, relevant) pairs."""
    rrs = [reciprocal_rank(ret, rel) for ret, rel in cases]
    return sum(rrs) / len(rrs) if rrs else 0.0


def dcg_at_k(retrieved: Sequence[str], relevant: Iterable[str], k: int) -> float:
    """Binary-gain discounted cumulative gain at k."""
    rel = set(relevant)
    dcg = 0.0
    for i, r in enumerate(list(retrieved)[:k]):
        if r in rel:
            dcg += 1.0 / math.log2(i + 2)  # i is 0-based; rank 1 -> log2(2)=1
    return dcg


def ndcg_at_k(retrieved: Sequence[str], relevant: Iterable[str], k: int) -> float:
    """DCG@k normalized by the ideal DCG@k (1.0 = perfect ranking)."""
    rel = set(relevant)
    if not rel:
        return 0.0
    ideal_hits = min(len(rel), k)
    idcg = sum(1.0 / math.log2(i + 2) for i in range(ideal_hits))
    if idcg == 0.0:
        return 0.0
    return dcg_at_k(retrieved, rel, k) / idcg


def aggregate(values: List[float]) -> float:
    """Mean of a list of per-case metric values (0.0 if empty)."""
    return sum(values) / len(values) if values else 0.0
