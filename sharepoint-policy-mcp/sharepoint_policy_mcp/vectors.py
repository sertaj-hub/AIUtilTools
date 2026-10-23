"""A small on-disk vector index: cosine similarity over normalised rows.

NumPy over a persisted `.npz` is enough for a policy corpus, which is
thousands of chunks rather than millions, and it keeps the prototype free of
a service to stand up. The surface is deliberately the one Azure AI Search
also offers, so swapping it is a new class rather than a rewrite.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

INDEX_VERSION = 1


class VectorIndexError(RuntimeError):
    """The index on disk cannot be used as-is."""


class VectorIndex:
    """Chunk ids and their unit-length embeddings, searchable by cosine."""

    def __init__(
        self,
        chunk_ids: list[str],
        vectors: np.ndarray,
        embedder_name: str,
    ) -> None:
        if len(chunk_ids) != vectors.shape[0]:
            raise VectorIndexError(
                f"{len(chunk_ids)} chunk ids but {vectors.shape[0]} vectors"
            )
        self.chunk_ids = chunk_ids
        self.vectors = vectors.astype(np.float32, copy=False)
        self.embedder_name = embedder_name
        self._position = {cid: i for i, cid in enumerate(chunk_ids)}

    def __len__(self) -> int:
        return len(self.chunk_ids)

    @property
    def dimensions(self) -> int:
        return int(self.vectors.shape[1]) if len(self) else 0

    def search(self, query: np.ndarray, limit: int | None = None) -> list[tuple[str, float]]:
        """Return (chunk_id, cosine) pairs, best first, dropping non-positives.

        Rows are unit length and so is the query, so the dot product is the
        cosine. A zero or negative score means no lexical or semantic overlap
        worth returning; keeping those would pad the page with noise that the
        fusion step would then have to rank.
        """
        if len(self) == 0:
            return []
        scores = self.vectors @ query.astype(np.float32)
        order = np.argsort(-scores, kind="stable")
        out: list[tuple[str, float]] = []
        for i in order:
            score = float(scores[i])
            if score <= 0.0:
                break
            out.append((self.chunk_ids[i], round(score, 6)))
            if limit is not None and len(out) >= limit:
                break
        return out

    def vector_for(self, chunk_id: str) -> np.ndarray | None:
        position = self._position.get(chunk_id)
        return None if position is None else self.vectors[position]

    # -- persistence -----------------------------------------------------

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(
            path,
            version=np.array([INDEX_VERSION]),
            chunk_ids=np.array(self.chunk_ids, dtype=object),
            vectors=self.vectors,
            embedder_name=np.array([self.embedder_name], dtype=object),
        )

    @classmethod
    def load(cls, path: Path, expect_embedder: str | None = None) -> "VectorIndex":
        if not path.exists():
            raise VectorIndexError(f"No vector index at {path}")
        with np.load(path, allow_pickle=True) as data:
            version = int(data["version"][0])
            if version != INDEX_VERSION:
                raise VectorIndexError(
                    f"Vector index at {path} is version {version}; this build "
                    f"writes version {INDEX_VERSION}. Re-run ingestion."
                )
            chunk_ids = [str(c) for c in data["chunk_ids"]]
            vectors = data["vectors"]
            embedder_name = str(data["embedder_name"][0])

        if expect_embedder is not None and embedder_name != expect_embedder:
            # Vectors from two different models share a space only by
            # coincidence. Comparing them returns confident nonsense, which is
            # the worst failure mode available to a retrieval system.
            raise VectorIndexError(
                f"Vector index at {path} was built with {embedder_name!r} but "
                f"{expect_embedder!r} is configured. Re-run ingestion."
            )
        return cls(chunk_ids, vectors, embedder_name)
