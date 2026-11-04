"""Unit tests for IR metrics with hand-computed expected values."""
from __future__ import annotations

import math

import pytest

from domain.evaluations.ir_metrics import (
    hit_at_k, precision_at_k, recall_at_k, reciprocal_rank, ndcg_at_k, report,
)

RANKED = ["a", "b", "c", "d"]
RELEVANT = {"b", "d"}


def test_hit_at_k():
    assert hit_at_k(RANKED, RELEVANT, 1) == 0.0   # 'a' not relevant
    assert hit_at_k(RANKED, RELEVANT, 2) == 1.0   # 'b' relevant


def test_precision_at_k():
    assert precision_at_k(RANKED, RELEVANT, 2) == 0.5
    assert precision_at_k(RANKED, RELEVANT, 4) == 0.5


def test_recall_at_k():
    assert recall_at_k(RANKED, RELEVANT, 2) == 0.5
    assert recall_at_k(RANKED, RELEVANT, 4) == 1.0


def test_reciprocal_rank():
    assert reciprocal_rank(RANKED, RELEVANT) == 0.5   # first relevant at rank 2


def test_ndcg_at_k():
    dcg = 1 / math.log2(3) + 1 / math.log2(5)        # b@2, d@4
    idcg = 1 / math.log2(2) + 1 / math.log2(3)       # ideal: 2 relevant first
    assert ndcg_at_k(RANKED, RELEVANT, 4) == pytest.approx(dcg / idcg, rel=1e-6)


def test_report_shape():
    cases = [(RANKED, RELEVANT), (["b", "a"], {"b"})]
    r = report(cases, ks=(1, 3))
    assert r["queries"] == 2
    assert set(r) >= {"mrr", "hit@1", "precision@3", "recall@3", "ndcg@1"}
