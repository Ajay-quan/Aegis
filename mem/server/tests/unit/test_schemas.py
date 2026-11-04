"""Unit tests for core schemas."""
import pytest
from datetime import datetime, timezone
from pydantic import ValidationError

from core.schemas.memory import (
    MemoryItem, MemoryType, MemoryStatus, SourceType,
    Observation, Reflection, FactRecord, RetrievalQuery,
    RetrievalCandidate, WorkingMemory,
)


class TestMemoryItem:
    def test_create_with_required_fields(self):
        m = MemoryItem(
            namespace="user:123",
            user_id="123",
            content="Test content",
        )
        assert m.memory_id is not None
        assert m.memory_type == MemoryType.OBSERVATION
        assert m.status == MemoryStatus.ACTIVE
        assert m.version == 1

    def test_empty_content_raises(self):
        with pytest.raises(ValidationError):
            MemoryItem(namespace="user:123", user_id="123", content="")

    def test_empty_namespace_raises(self):
        with pytest.raises(ValidationError):
            MemoryItem(namespace="   ", user_id="123", content="test")

    def test_importance_score_bounds(self):
        with pytest.raises(ValidationError):
            MemoryItem(namespace="u:1", user_id="1", content="x", importance_score=1.5)
        with pytest.raises(ValidationError):
            MemoryItem(namespace="u:1", user_id="1", content="x", importance_score=-0.1)

    def test_bump_access(self):
        m = MemoryItem(namespace="u:1", user_id="1", content="x")
        assert m.access_count == 0
        m.bump_access()
        assert m.access_count == 1

    def test_supersede(self):
        m = MemoryItem(namespace="u:1", user_id="1", content="x")
        m.supersede()
        assert m.status == MemoryStatus.SUPERSEDED

    def test_unique_ids(self):
        m1 = MemoryItem(namespace="u:1", user_id="1", content="x")
        m2 = MemoryItem(namespace="u:1", user_id="1", content="x")
        assert m1.memory_id != m2.memory_id


class TestObservation:
    def test_create_observation(self):
        obs = Observation(session_id="s1", user_id="u1", content="test")
        assert obs.observation_id is not None
        assert obs.processed is False


class TestFactRecord:
    def test_create_fact(self):
        fact = FactRecord(
            user_id="u1",
            namespace="user:u1",
            subject="user",
            predicate="lives_in",
            object="San Francisco",
        )
        assert fact.obj == "San Francisco"

    def test_fact_alias(self):
        fact = FactRecord(
            user_id="u1",
            namespace="user:u1",
            subject="user",
            predicate="works_at",
            object="Acme Corp",
        )
        assert fact.obj == "Acme Corp"


class TestRetrievalQuery:
    def test_default_top_k(self):
        q = RetrievalQuery(query_text="test", user_id="u1")
        assert q.top_k == 5

    def test_top_k_bounds(self):
        with pytest.raises(ValidationError):
            RetrievalQuery(query_text="t", user_id="u1", top_k=0)
        with pytest.raises(ValidationError):
            RetrievalQuery(query_text="t", user_id="u1", top_k=100)


class TestWorkingMemory:
    def test_add_turn(self):
        wm = WorkingMemory(session_id="s1", agent_id="a1", user_id="u1")
        wm.add_turn("user", "Hello")
        wm.add_turn("assistant", "Hi!")
        assert len(wm.conversation_turns) == 2

    def test_add_tool_output_truncates(self):
        wm = WorkingMemory(session_id="s1", agent_id="a1", user_id="u1")
        for i in range(25):
            wm.add_tool_output(f"tool_{i}", f"output_{i}")
        assert len(wm.recent_tool_outputs) <= 20
