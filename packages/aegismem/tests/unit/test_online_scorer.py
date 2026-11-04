"""Unit tests for the AegisMem-CL online ranking policy."""
from __future__ import annotations

from domain.learning.features import FEATURE_NAMES
from domain.learning.online_scorer import OnlineRankingPolicy


def _base():
    return {f: 1.0 / len(FEATURE_NAMES) for f in FEATURE_NAMES}


def test_weights_are_convex():
    p = OnlineRankingPolicy(_base())
    w = p.weights("ns")
    assert set(w) == set(FEATURE_NAMES)
    assert all(v >= 0 for v in w.values())
    assert abs(sum(w.values()) - 1.0) < 1e-9


def test_predict_is_linear():
    p = OnlineRankingPolicy(_base())
    feats = {f: 0.0 for f in FEATURE_NAMES}
    feats["semantic"] = 1.0
    # uniform weights => predict == weight on the single active feature
    assert abs(p.predict("ns", feats) - (1.0 / len(FEATURE_NAMES))) < 1e-9


def test_update_shifts_weight_toward_rewarded_feature():
    p = OnlineRankingPolicy(_base(), learning_rate=0.2, ewc_lambda=0.0)
    feats = {f: 0.0 for f in FEATURE_NAMES}
    feats["lexical"] = 1.0
    before = p.weights("ns")["lexical"]
    for _ in range(50):
        p.update("ns", feats, reward=1.0)
    after = p.weights("ns")["lexical"]
    assert after > before
    # still a valid simplex
    assert abs(sum(p.weights("ns").values()) - 1.0) < 1e-9


def test_namespace_isolation():
    p = OnlineRankingPolicy(_base(), learning_rate=0.3, ewc_lambda=0.0)
    feats = {f: 0.0 for f in FEATURE_NAMES}
    feats["recency"] = 1.0
    for _ in range(30):
        p.update("tenant-a", feats, reward=1.0)
    # tenant-b was never touched => still the base prior
    assert p.weights("tenant-b") == p.weights("untouched-too")
    assert p.weights("tenant-a")["recency"] > p.weights("tenant-b")["recency"]


def test_learning_improves_ranking():
    p = OnlineRankingPolicy(_base(), learning_rate=0.2, ewc_lambda=0.0)
    # relevant candidate is high on 'importance'; decoy is high on 'semantic'
    relevant = {f: 0.1 for f in FEATURE_NAMES}; relevant["importance"] = 1.0
    decoy = {f: 0.1 for f in FEATURE_NAMES}; decoy["semantic"] = 1.0
    for _ in range(80):
        p.update("ns", relevant, reward=1.0)
        p.update("ns", decoy, reward=0.0)
    assert p.predict("ns", relevant) > p.predict("ns", decoy)


def test_all_zero_features_keep_simplex():
    p = OnlineRankingPolicy(_base(), learning_rate=0.5, ewc_lambda=0.0)
    zeros = {f: 0.0 for f in FEATURE_NAMES}
    p.update("ns", zeros, reward=1.0)
    w = p.weights("ns")
    assert abs(sum(w.values()) - 1.0) < 1e-9
    assert all(v >= 0 for v in w.values())


def test_consolidate_sets_anchor_and_counts():
    p = OnlineRankingPolicy(_base(), learning_rate=0.1)
    feats = {f: 0.5 for f in FEATURE_NAMES}
    p.update("ns", feats, reward=1.0)
    assert p.update_count("ns") == 1
    p.consolidate("ns")  # must not raise
    stats = p.stats()
    assert "ns" in stats and "weights" in stats["ns"]
