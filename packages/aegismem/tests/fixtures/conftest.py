"""Shared test fixtures for AegisMem tests."""
from __future__ import annotations

import pytest
import pytest_asyncio

from adapters.llm.mock_client import MockLLMClient
from adapters.embeddings.backend import MockEmbeddingBackend
from adapters.vector_store.qdrant_store import InMemoryVectorStore
from adapters.graph_store.neo4j_store import MockGraphStore
from core.schemas.memory import MemoryItem, MemoryType, SourceType, Observation


# Tests historically call this MockPostgresStore; it is the real in-memory adapter.
from adapters.relational_store.memory_store import InMemoryMemoryStore as MockPostgresStore  # noqa: E402,F401


@pytest.fixture
def mock_db():
    return MockPostgresStore()


@pytest.fixture
def mock_embed():
    return MockEmbeddingBackend(dim=384)


@pytest.fixture
def mock_llm():
    client = MockLLMClient()
    # Register common responses
    client.register_response(
        "contradicts",
        '{"contradicts": true, "confidence": 0.9, "description": "Conflicting location", "resolution_suggestion": "Use newer"}'
    )
    client.register_response(
        "reflection",
        '{"reflections": [{"content": "User shows strong interest in AI", "confidence": 0.85, "supporting_indices": [0, 1]}]}'
    )
    client.register_response(
        "update",
        '{"action": "supersede", "reason": "New info replaces old", "merged_content": "user moved to Austin", "confidence": 0.9}'
    )
    return client


@pytest_asyncio.fixture
async def mock_vector_store():
    store = InMemoryVectorStore()
    await store.initialize(dimension=384)
    return store


@pytest.fixture
def mock_graph():
    return MockGraphStore()


@pytest.fixture
def sample_memory(mock_db) -> MemoryItem:
    return MemoryItem(
        namespace="user:test123",
        user_id="test123",
        agent_id="agent1",
        memory_type=MemoryType.OBSERVATION,
        content="User likes Python and machine learning",
        source_type=SourceType.USER_MESSAGE,
        importance_score=0.7,
    )


@pytest.fixture
def sample_observation() -> Observation:
    return Observation(
        session_id="sess1",
        user_id="test123",
        agent_id="agent1",
        content="User mentioned they prefer remote work",
        source_type=SourceType.USER_MESSAGE,
    )
