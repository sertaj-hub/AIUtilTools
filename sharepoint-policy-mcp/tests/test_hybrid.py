"""Reciprocal rank fusion."""

import pytest

from sharepoint_policy_mcp.hybrid import rank_ids, reciprocal_rank_fusion


def test_agreement_between_retrievers_wins():
    fused = reciprocal_rank_fusion({"a": ["x", "y", "z"], "b": ["x", "z", "y"]})
    assert fused[0].doc_id == "x"


def test_a_document_only_one_retriever_found_still_appears():
    fused = reciprocal_rank_fusion({"lexical": ["a"], "dense": ["b"]})
    assert {f.doc_id for f in fused} == {"a", "b"}


def test_ranks_record_where_each_retriever_placed_it():
    fused = reciprocal_rank_fusion({"lexical": ["a", "b"], "dense": ["b"]})
    by_id = {f.doc_id: f for f in fused}
    assert by_id["b"].ranks == {"lexical": 2, "dense": 1}
    assert by_id["a"].ranks == {"lexical": 1}


def test_scores_are_independent_of_the_retrievers_own_scales():
    # The whole point of RRF: only the ordering is used, so a retriever with
    # unbounded scores cannot drown out one bounded to [-1, 1].
    first = reciprocal_rank_fusion({"a": ["p", "q"], "b": ["q", "p"]})
    second = reciprocal_rank_fusion({"a": ["p", "q"], "b": ["q", "p"]})
    assert [f.doc_id for f in first] == [f.doc_id for f in second]


def test_one_empty_ranking_degrades_to_the_other():
    fused = reciprocal_rank_fusion({"lexical": ["a", "b", "c"], "dense": []})
    assert [f.doc_id for f in fused] == ["a", "b", "c"]


def test_all_empty_gives_nothing():
    assert reciprocal_rank_fusion({"lexical": [], "dense": []}) == []


def test_weights_shift_the_balance():
    balanced = reciprocal_rank_fusion({"lexical": ["a", "b"], "dense": ["b", "a"]})
    tilted = reciprocal_rank_fusion(
        {"lexical": ["a", "b"], "dense": ["b", "a"]}, weights={"dense": 5.0}
    )
    assert balanced[0].doc_id == "a"
    assert tilted[0].doc_id == "b"


def test_a_zero_weight_excludes_a_retriever_entirely():
    fused = reciprocal_rank_fusion(
        {"lexical": ["a"], "dense": ["b"]}, weights={"dense": 0.0}
    )
    assert [f.doc_id for f in fused] == ["a"]


def test_ordering_is_deterministic_on_ties():
    fused = reciprocal_rank_fusion({"a": ["x"], "b": ["y"]})
    assert [f.doc_id for f in fused] == ["x", "y"]


def test_limit_truncates():
    fused = reciprocal_rank_fusion({"a": ["x", "y", "z"]}, limit=2)
    assert len(fused) == 2


def test_k_must_be_positive():
    with pytest.raises(ValueError, match="at least 1"):
        reciprocal_rank_fusion({"a": ["x"]}, k=0)


def test_rank_ids_drops_scores_and_keeps_order():
    assert rank_ids([("a", 0.9), ("b", 0.2)]) == ["a", "b"]
