"""The offline embedder and the vector index it feeds."""

import numpy as np
import pytest

from sharepoint_policy_mcp.embedder import HashingEmbedder
from sharepoint_policy_mcp.vectors import VectorIndex, VectorIndexError


async def test_vectors_are_unit_length():
    matrix = await HashingEmbedder(64).embed_documents(["suspicious activity report"])
    assert np.isclose(np.linalg.norm(matrix[0]), 1.0)


async def test_embedding_is_deterministic():
    first = await HashingEmbedder(64).embed_documents(["currency transaction report"])
    second = await HashingEmbedder(64).embed_documents(["currency transaction report"])
    assert np.array_equal(first, second)


async def test_shape_follows_the_configured_dimensions():
    matrix = await HashingEmbedder(128).embed_documents(["a", "b", "c"])
    assert matrix.shape == (3, 128)


async def test_no_texts_returns_an_empty_matrix_not_an_error():
    matrix = await HashingEmbedder(32).embed_documents([])
    assert matrix.shape == (0, 32)


async def test_text_with_no_indexable_tokens_is_a_zero_vector_not_nan():
    # Dividing by a zero norm would give NaN, which poisons every later
    # comparison silently.
    matrix = await HashingEmbedder(32).embed_documents(["a的 ,. !"])
    assert not np.isnan(matrix).any()


async def test_lexical_overlap_scores_higher_than_none():
    embedder = HashingEmbedder(512)
    matrix = await embedder.embed_documents(
        ["suspicious activity report filing deadline", "training completion tracking"]
    )
    query = await embedder.embed_query("suspicious activity report deadline")
    assert float(matrix[0] @ query) > float(matrix[1] @ query)


async def test_the_embedder_declares_that_it_is_not_semantic():
    # It is a hashing vectoriser. Paraphrase with no shared words scores zero,
    # which is exactly the gap a real embedder exists to close.
    embedder = HashingEmbedder(512)
    assert embedder.is_semantic is False
    matrix = await embedder.embed_documents(["file a SAR within thirty days"])
    paraphrase = await embedder.embed_query("deadline for submitting the report")
    assert float(matrix[0] @ paraphrase) == pytest.approx(0.0, abs=1e-6)


def test_tiny_dimensions_are_refused():
    with pytest.raises(ValueError, match="at least 16"):
        HashingEmbedder(4)


# -- VectorIndex ---------------------------------------------------------


async def index(texts, ids=None, dims=128):
    embedder = HashingEmbedder(dims)
    matrix = await embedder.embed_documents(texts)
    return (
        VectorIndex(ids or [f"id-{i}" for i in range(len(texts))], matrix, embedder.name),
        embedder,
    )


async def test_search_returns_the_closest_first():
    idx, embedder = await index(
        [
            "suspicious activity report filing deadline",
            "currency transaction report threshold",
            "independent testing of the programme",
        ]
    )
    results = idx.search(await embedder.embed_query("SAR filing deadline"))
    assert results
    assert results[0][0] == "id-0"


async def test_search_drops_non_positive_scores():
    idx, embedder = await index(["training completion tracking"])
    assert idx.search(await embedder.embed_query("zzzqqx unrelated")) == []


async def test_search_respects_a_limit():
    idx, embedder = await index(["report one", "report two", "report three"])
    assert len(idx.search(await embedder.embed_query("report"), limit=2)) == 2


async def test_empty_index_searches_safely():
    empty = VectorIndex([], np.zeros((0, 16), dtype=np.float32), "hashing-16")
    assert len(empty) == 0
    assert empty.search(np.zeros(16, dtype=np.float32)) == []


async def test_mismatched_ids_and_vectors_are_refused():
    matrix = await HashingEmbedder(32).embed_documents(["a", "b"])
    with pytest.raises(VectorIndexError, match="2 vectors"):
        VectorIndex(["only-one"], matrix, "hashing-32")


async def test_index_round_trips_through_disk(tmp_path):
    idx, embedder = await index(["suspicious activity report", "training records"])
    path = tmp_path / "vectors.npz"
    idx.save(path)

    loaded = VectorIndex.load(path, expect_embedder=embedder.name)
    assert loaded.chunk_ids == idx.chunk_ids
    assert loaded.embedder_name == embedder.name
    assert np.array_equal(loaded.vectors, idx.vectors)
    assert loaded.search(await embedder.embed_query("suspicious activity"))[0][0] == "id-0"


async def test_loading_with_a_different_embedder_is_refused(tmp_path):
    # Vectors from two models share a space only by coincidence. Comparing
    # them returns confident nonsense, the worst failure a retriever has.
    idx, _ = await index(["anything"])
    path = tmp_path / "vectors.npz"
    idx.save(path)
    with pytest.raises(VectorIndexError, match="Re-run ingestion"):
        VectorIndex.load(path, expect_embedder="voyage-3-large")


def test_loading_a_missing_index_says_so(tmp_path):
    with pytest.raises(VectorIndexError, match="No vector index"):
        VectorIndex.load(tmp_path / "absent.npz")


async def test_vector_for_returns_a_stored_row(tmp_path):
    idx, _ = await index(["alpha", "beta"])
    assert idx.vector_for("id-1") is not None
    assert idx.vector_for("missing") is None
