"""
Retrieval evaluation
=====================

A stdlib-only, runnable evaluation of *retrieval quality* — not "the code runs."
This is the in-repo proof artifact: a gold set of (query -> expected memory)
cases scored with the standard IR metrics (recall@k, precision@k, MRR, nDCG@k),
so retrieval changes are measured against numbers, not vibes, and regressions
are caught by CI.

It's also the harness the bigger proof builds on (memory-on vs memory-off on a
coding-agent benchmark; see ``eval/swebench/`` at the repo root).
"""

from rainman.eval.metrics import (
    recall_at_k,
    precision_at_k,
    reciprocal_rank,
    mean_reciprocal_rank,
    dcg_at_k,
    ndcg_at_k,
)
from rainman.eval.harness import EvalCase, evaluate_retrieval

__all__ = [
    "recall_at_k",
    "precision_at_k",
    "reciprocal_rank",
    "mean_reciprocal_rank",
    "dcg_at_k",
    "ndcg_at_k",
    "EvalCase",
    "evaluate_retrieval",
]
