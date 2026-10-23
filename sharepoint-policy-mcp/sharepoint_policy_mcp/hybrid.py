"""Fusing the lexical and dense rankings.

Reciprocal Rank Fusion, not score normalisation. BM25 scores are unbounded
and corpus-dependent; cosine similarities sit in [-1, 1]. Any scheme that
adds them has to invent a scale factor, and that factor silently becomes the
most important tuning parameter in the system -- one nobody set deliberately
and nobody can explain to a reviewer.

RRF uses only the ordering each retriever produced, which is the part each is
actually good at. It needs no tuning, no shared scale, and it degrades
gracefully when one retriever returns nothing.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

# The constant from the original RRF paper. It damps the contribution of top
# ranks so that one retriever's confident first place cannot by itself
# outvote broad agreement further down.
DEFAULT_K = 60


@dataclass(frozen=True)
class Fused:
    """One document id with its fused score and where each retriever put it."""

    doc_id: str
    score: float
    ranks: dict[str, int]  # retriever name -> 1-based rank, absent if unranked


def reciprocal_rank_fusion(
    rankings: dict[str, Sequence[str]],
    weights: dict[str, float] | None = None,
    k: int = DEFAULT_K,
    limit: int | None = None,
) -> list[Fused]:
    """Fuse named rankings of document ids into one ordered list.

    `rankings` maps a retriever name to its ordered ids, best first. `weights`
    scales each retriever's contribution; a retriever absent from `weights`
    counts as 1.0.
    """
    if k < 1:
        raise ValueError("k must be at least 1")

    weights = weights or {}
    scores: dict[str, float] = {}
    ranks: dict[str, dict[str, int]] = {}

    for name, ordered in rankings.items():
        weight = float(weights.get(name, 1.0))
        if weight == 0.0:
            continue
        for position, doc_id in enumerate(ordered, start=1):
            scores[doc_id] = scores.get(doc_id, 0.0) + weight / (k + position)
            ranks.setdefault(doc_id, {})[name] = position

    fused = [
        Fused(doc_id=doc_id, score=round(score, 8), ranks=ranks[doc_id])
        for doc_id, score in scores.items()
    ]
    # Ties broken by id so repeating a query gives the same order.
    fused.sort(key=lambda f: (-f.score, f.doc_id))
    return fused if limit is None else fused[:limit]


def rank_ids(pairs: Iterable[tuple[str, float]]) -> list[str]:
    """Drop the scores from a (id, score) ranking, keeping the order."""
    return [doc_id for doc_id, _ in pairs]
