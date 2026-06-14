"""
Retrieval eval harness
=======================

Runs a gold set of cases through ``engine.recall`` and reports aggregate IR
metrics. Task-state conditioning (M2) and the optional semantic provider (M7)
are supported per-case so the same harness measures every retrieval mode.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

from rainman.eval.metrics import (
    aggregate,
    ndcg_at_k,
    precision_at_k,
    recall_at_k,
    reciprocal_rank,
)


@dataclass
class EvalCase:
    """One retrieval test: a query and the ids that should come back."""
    query: str
    relevant_ids: Sequence[str]
    context_files: Optional[List[str]] = None
    error_signature: Optional[str] = None
    note: str = ""


@dataclass
class EvalReport:
    k: int
    n_cases: int
    recall_at_k: float
    precision_at_k: float
    mrr: float
    ndcg_at_k: float
    per_case: List[Dict[str, Any]] = field(default_factory=list)

    def summary(self) -> str:
        return (
            f"cases={self.n_cases}  recall@{self.k}={self.recall_at_k:.3f}  "
            f"precision@{self.k}={self.precision_at_k:.3f}  MRR={self.mrr:.3f}  "
            f"nDCG@{self.k}={self.ndcg_at_k:.3f}"
        )


def evaluate_retrieval(
    engine,
    cases: Sequence[EvalCase],
    k: int = 5,
    limit: Optional[int] = None,
    semantic_provider=None,
) -> EvalReport:
    """Run ``cases`` through ``engine.recall`` and aggregate IR metrics."""
    limit = limit or k
    recalls, precisions, rrs, ndcgs, per_case = [], [], [], [], []

    for case in cases:
        results = engine.recall(
            case.query,
            limit=limit,
            context_files=case.context_files,
            error_signature=case.error_signature,
            semantic_provider=semantic_provider,
        )
        retrieved = [r.memory.id for r in results]
        rel = case.relevant_ids

        r = recall_at_k(retrieved, rel, k)
        p = precision_at_k(retrieved, rel, k)
        rr = reciprocal_rank(retrieved, rel)
        nd = ndcg_at_k(retrieved, rel, k)
        recalls.append(r)
        precisions.append(p)
        rrs.append(rr)
        ndcgs.append(nd)
        per_case.append({
            "query": case.query,
            "relevant": list(rel),
            "retrieved": retrieved,
            "recall_at_k": r,
            "reciprocal_rank": rr,
            "hit": rr > 0.0,
        })

    return EvalReport(
        k=k,
        n_cases=len(cases),
        recall_at_k=aggregate(recalls),
        precision_at_k=aggregate(precisions),
        mrr=aggregate(rrs),
        ndcg_at_k=aggregate(ndcgs),
        per_case=per_case,
    )
