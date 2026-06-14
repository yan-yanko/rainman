"""
Rank fusion
===========

Reciprocal Rank Fusion (Cormack, Clarke & Büttcher, SIGIR 2009) — combines
multiple ranked lists by *rank*, not score, so a lexical ranking and a dense
(semantic) ranking on different scales fuse without calibration. Pure stdlib.

The key property for Rainman: with a single input ranking (no semantic lane
installed) the fused order is identical to that ranking — so the optional
semantic lane adds zero behavioral change when absent.
"""

from typing import Dict, List

RRF_K = 60  # standard dampening constant from the RRF paper


def reciprocal_rank_fusion(rankings: List[List[str]], k: int = RRF_K) -> Dict[str, float]:
    """Fuse ranked lists of ids into ``{id: fused_score}`` (higher = better).

    Each list contributes ``1 / (k + rank)`` (rank is 0-based) for every id it
    contains. Ids absent from a list simply get no contribution from it.
    """
    scores: Dict[str, float] = {}
    for ranking in rankings:
        for rank, doc_id in enumerate(ranking):
            scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (k + rank + 1)
    return scores
