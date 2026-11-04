"""Unit tests for sparse lexical retrieval (BM25) and rank fusion."""
from __future__ import annotations

from domain.memory.lexical import (
    BM25Index, reciprocal_rank_fusion, normalize_scores, tokenize,
)


CORPUS = [
    ("m1", "Alice prefers Python and FAISS for local vector search"),
    ("m2", "The user deploys demos on AWS Free Tier EC2 instances"),
    ("m3", "Bob enjoys hiking and photography on weekends"),
    ("m4", "Python is used for the FAISS embedding pipeline"),
]


def test_tokenize_lowercases_and_splits():
    assert tokenize("Hello, World! 42") == ["hello", "world", "42"]


def test_bm25_ranks_keyword_match_first():
    idx = BM25Index.build(CORPUS)
    results = idx.search("FAISS Python", top_k=3)
    ids = [doc_id for doc_id, _ in results]
    # m1 and m4 both contain FAISS + Python and should outrank unrelated docs.
    assert set(ids[:2]) == {"m1", "m4"}
    assert "m3" not in ids


def test_bm25_zero_for_no_overlap():
    idx = BM25Index.build(CORPUS)
    results = idx.search("quantum chromodynamics")
    assert results == []


def test_bm25_empty_corpus_is_safe():
    idx = BM25Index.build([])
    assert idx.search("anything") == []


def test_rrf_rewards_agreement_across_lists():
    # A doc ranked highly in BOTH lists should win over one ranked high in one.
    dense = ["a", "b", "c"]
    sparse = ["b", "a", "d"]
    fused = reciprocal_rank_fusion([dense, sparse], k=60)
    fused_ids = [doc_id for doc_id, _ in fused]
    # 'a' (ranks 1,2) and 'b' (ranks 2,1) lead; both beat single-list items.
    assert set(fused_ids[:2]) == {"a", "b"}
    assert fused_ids.index("a") < fused_ids.index("c")


def test_rrf_handles_disjoint_lists():
    fused = reciprocal_rank_fusion([["a"], ["b"]], k=60)
    assert {doc_id for doc_id, _ in fused} == {"a", "b"}


def test_normalize_scores_min_max():
    norm = normalize_scores([("a", 10.0), ("b", 5.0), ("c", 0.0)])
    assert norm["a"] == 1.0
    assert norm["c"] == 0.0
    assert 0.0 < norm["b"] < 1.0


def test_normalize_scores_equal_values():
    norm = normalize_scores([("a", 3.0), ("b", 3.0)])
    assert norm == {"a": 1.0, "b": 1.0}
