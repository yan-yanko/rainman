"""
Optional semantic lane (M7)
===========================

The stdlib core ships only the *seam*: a provider protocol, cosine similarity,
and a loader that returns ``None`` unless an embedding backend is installed.
This is what lets the synonym/abbreviation gap (``auth`` ≠ ``authentication``)
be closed WITHOUT a dependency in the zero-dep client — the real model arrives
via ``pip install rainman[semantic]`` and the buyer virtue is reframed from
"stdlib-only" to "no data leaves your machine" (a local model is still local).

A provider implements:

    class Provider:
        name: str
        def embed(self, texts: list[str]) -> list[list[float]]: ...

``load_provider()`` attempts, in order, an installed ``rainman_semantic``
backend (the extra). If nothing is importable it returns ``None`` and the
engine runs pure-lexical — identical to today. No third-party import happens at
module import time; the zero-dependency guarantee of the core is preserved.
"""

import math
from typing import List, Optional, Protocol, Sequence, runtime_checkable


@runtime_checkable
class SemanticProvider(Protocol):
    """A local embedding backend. Must run offline, no network/egress."""

    name: str

    def embed(self, texts: Sequence[str]) -> List[List[float]]:
        ...


class _Model2VecProvider:
    """Built-in local provider backed by model2vec (potion-base-8M by default).

    Static embeddings: a token->vector lookup + mean pool, ~8MB, numpy-only, no
    torch and no network at query time. model2vec is imported lazily here so the
    core package never depends on it.
    """

    name = "model2vec:potion-base-8M"

    def __init__(self, model: str = "minishlab/potion-base-8M"):
        from model2vec import StaticModel  # lazy: only when the extra is present

        self._model = StaticModel.from_pretrained(model)

    def embed(self, texts: Sequence[str]) -> List[List[float]]:
        return [list(map(float, v)) for v in self._model.encode(list(texts))]


def load_provider() -> Optional[SemanticProvider]:
    """Return an installed local embedding provider, or None if none is present.

    Resolution order: (1) an externally-registered ``rainman_semantic`` package,
    (2) the built-in model2vec backend (``pip install rainman[semantic]``).
    Every import failure is the normal default path and is swallowed silently —
    the core stays dependency-free and runs pure-lexical.
    """
    try:  # pragma: no cover - exercised only when an external provider exists
        from rainman_semantic import Provider  # type: ignore

        return Provider()
    except Exception:
        pass
    try:  # pragma: no cover - exercised only when the extra is installed
        return _Model2VecProvider()
    except Exception:
        return None


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    """Cosine similarity of two equal-length vectors, in [-1, 1] (0 if degenerate)."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)
