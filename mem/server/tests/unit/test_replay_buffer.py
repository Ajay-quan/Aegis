"""Unit tests for the AegisMem-CL replay buffer."""
from __future__ import annotations

from domain.learning.replay import CandidateRecord, ReplayBuffer


def _records():
    return [
        CandidateRecord(memory_id="m1", features={"semantic": 0.9}, served_rank=1, score=0.8),
        CandidateRecord(memory_id="m2", features={"semantic": 0.4}, served_rank=2, score=0.5),
    ]


def test_log_and_get():
    buf = ReplayBuffer(capacity=10)
    buf.log("q1", "u1", "ns", "query text", _records())
    inter = buf.get("q1")
    assert inter is not None
    assert inter.user_id == "u1" and len(inter.candidates) == 2
    assert inter.candidate("m1").memory_id == "m1"
    assert inter.candidate("missing") is None


def test_attach_reward_labels_example():
    buf = ReplayBuffer(capacity=10)
    buf.log("q1", "u1", "ns", "q", _records())
    assert buf.attach_reward("q1", "m1", 1.0) is True
    assert buf.get("q1").candidate("m1").reward == 1.0
    assert buf.labeled_count() == 1
    # unknown query / memory
    assert buf.attach_reward("nope", "m1", 1.0) is False
    assert buf.attach_reward("q1", "nope", 1.0) is False


def test_capacity_evicts_oldest():
    buf = ReplayBuffer(capacity=2)
    buf.log("q1", "u", "ns", "a", _records())
    buf.log("q2", "u", "ns", "b", _records())
    buf.log("q3", "u", "ns", "c", _records())
    assert len(buf) == 2
    assert buf.get("q1") is None  # evicted
    assert buf.get("q3") is not None


def test_sample_respects_namespace_and_size():
    buf = ReplayBuffer(capacity=100, seed=1)
    buf.log("q1", "u", "alpha", "a", _records())
    buf.log("q2", "u", "beta", "b", _records())
    buf.attach_reward("q1", "m1", 1.0)
    buf.attach_reward("q2", "m1", 0.0)
    alpha = buf.sample(10, namespace="alpha")
    assert len(alpha) == 1 and alpha[0][2] == "alpha"
    assert len(buf.sample(10)) == 2


def test_persistence_roundtrip(tmp_path):
    buf = ReplayBuffer(capacity=10)
    buf.log("q1", "u1", "ns", "q", _records())
    buf.attach_reward("q1", "m1", 0.7)
    path = str(tmp_path / "replay.json")
    buf.save(path)

    restored = ReplayBuffer(capacity=10)
    restored.load(path)
    assert restored.get("q1") is not None
    assert restored.get("q1").candidate("m1").reward == 0.7
    assert restored.labeled_count() == 1
