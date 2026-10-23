"""Embedders: the protocol, and an offline one that needs no provider.

No provider is wired up yet, and the pipeline does not wait for one. Every
embedder satisfies the same three-member surface, so chunking, indexing,
fusion and their tests are built and exercised against `HashingEmbedder`
before anyone picks a vendor. Adding a hosted provider later is one file
implementing this protocol.

`HashingEmbedder` is **not** a semantic model and must not be mistaken for
one. It is a hashing vectoriser: tokens are hashed into a fixed number of
buckets and the vector is L2-normalised, which gives real lexical-overlap
similarity and nothing else. Paraphrase that shares no words scores zero --
precisely the gap a real embedder exists to close. It is here so the plumbing
has something deterministic and offline to run against, and `sp_ping` says
which embedder is live so nobody mistakes a test rig for retrieval quality.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from typing import Protocol

import numpy as np

from .search import tokenize


class Embedder(Protocol):
    """The surface the ingestion pipeline and the vector store depend on."""

    @property
    def name(self) -> str:
        """Identifies the model. Persisted with the index; a mismatch on load
        means the vectors were made by something else and cannot be compared."""
        ...

    @property
    def dimensions(self) -> int: ...

    @property
    def is_semantic(self) -> bool:
        """False for a test rig. Surfaced so callers can say so out loud."""
        ...

    async def embed_documents(self, texts: Sequence[str]) -> np.ndarray: ...

    async def embed_query(self, text: str) -> np.ndarray: ...


def _l2_normalise(matrix: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    # A chunk with no indexable tokens yields a zero vector. Dividing by zero
    # would give NaN, which poisons every later comparison silently; a zero
    # vector just scores zero against everything, which is the truth.
    norms[norms == 0] = 1.0
    return matrix / norms


class HashingEmbedder:
    """Deterministic, offline, lexical. A test rig, not a retrieval model."""

    def __init__(self, dimensions: int = 512) -> None:
        if dimensions < 16:
            raise ValueError("dimensions must be at least 16")
        self._dimensions = dimensions

    @property
    def name(self) -> str:
        return f"hashing-{self._dimensions}"

    @property
    def dimensions(self) -> int:
        return self._dimensions

    @property
    def is_semantic(self) -> bool:
        return False

    def _vector(self, text: str) -> np.ndarray:
        vector = np.zeros(self._dimensions, dtype=np.float32)
        for token in tokenize(text):
            digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
            bucket = int.from_bytes(digest[:4], "big") % self._dimensions
            # The sign bit spreads collisions instead of letting unrelated
            # tokens always reinforce each other.
            sign = 1.0 if digest[4] & 1 else -1.0
            vector[bucket] += sign
        return vector

    async def embed_documents(self, texts: Sequence[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, self._dimensions), dtype=np.float32)
        return _l2_normalise(np.vstack([self._vector(t) for t in texts]))

    async def embed_query(self, text: str) -> np.ndarray:
        return _l2_normalise(self._vector(text).reshape(1, -1))[0]
