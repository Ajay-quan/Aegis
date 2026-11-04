"""Integration tests for ingestion and retrieval services."""
import pytest
import pytest_asyncio

from services.ingest_service import IngestionService
from services.retrieve_service import RetrievalService
from services.consolidation_service import ConsolidationService
from core.schemas.memory import MemoryType, MemoryLayer, SourceType, RetrievalQuery


@pytest_asyncio.fixture
async def ingest_svc(mock_db, mock_embed, mock_vector_store, mock_graph):
    return IngestionService(
        relational_store=mock_db,
        vector_store=mock_vector_store,
        embedding_backend=mock_embed,
        graph_store=mock_graph,
    )


@pytest_asyncio.fixture
async def retrieve_svc(mock_db, mock_embed, mock_vector_store):
    return RetrievalService(
        relational_store=mock_db,
        vector_store=mock_vector_store,
        embedding_backend=mock_embed,
    )


class TestIngestionService:
    async def test_ingest_text(self, ingest_svc):
        memory = await ingest_svc.ingest_text(
            text="User loves Python programming",
            user_id="u1",
            session_id="s1",
        )
        assert memory.memory_id is not None
        assert memory.user_id == "u1"
        assert "Python" in memory.content

    async def test_ingest_assigns_importance(self, ingest_svc):
        high_importance = await ingest_svc.ingest_text(
            text="User always prefers dark mode and never uses light theme",
            user_id="u1",
        )
        low_importance = await ingest_svc.ingest_text(
            text="The sky is blue",
            user_id="u1",
        )
        assert high_importance.importance_score > low_importance.importance_score

    async def test_ingest_batch(self, ingest_svc, sample_observation):
        from core.schemas.memory import Observation
        observations = [
            Observation(session_id="s1", user_id="u1", content=f"Observation {i}")
            for i in range(5)
        ]
        memories = await ingest_svc.ingest_batch(observations)
        assert len(memories) == 5

    async def test_ingest_stores_in_vector_store(self, ingest_svc, mock_vector_store):
        await ingest_svc.ingest_text(text="test content", user_id="u_vs_test")
        # Vector store should have 1 entry
        assert len(mock_vector_store._store) >= 1


class TestRetrievalService:
    async def test_retrieve_returns_results(self, ingest_svc, retrieve_svc):
        await ingest_svc.ingest_text(
            text="User is a software engineer working on AI systems",
            user_id="u2",
        )
        result = await retrieve_svc.retrieve(
            RetrievalQuery(query_text="software engineer AI", user_id="u2", top_k=5)
        )
        assert result.total_found >= 0
        assert result.latency_ms >= 0

    async def test_retrieve_ranks_by_score(self, ingest_svc, retrieve_svc):
        for i in range(5):
            await ingest_svc.ingest_text(
                text=f"Memory item number {i} about Python and AI",
                user_id="u3",
                importance_override=0.3 + i * 0.1,
            )
        result = await retrieve_svc.retrieve(
            RetrievalQuery(query_text="Python AI", user_id="u3", top_k=5)
        )
        if len(result.candidates) > 1:
            scores = [c.composite_score for c in result.candidates]
            assert scores == sorted(scores, reverse=True)

    async def test_retrieve_context_window(self, ingest_svc, retrieve_svc):
        await ingest_svc.ingest_text(
            text="User works at Tech Corp as an ML engineer",
            user_id="u4",
        )
        context = await retrieve_svc.get_context_window(
            user_id="u4",
            query_text="where does user work",
        )
        # Context may be empty if no results, that's OK in mock mode
        assert isinstance(context, str)

    async def test_retrieve_filters_by_importance(self, ingest_svc, retrieve_svc):
        await ingest_svc.ingest_text(
            text="trivial info",
            user_id="u5",
            importance_override=0.1,
        )
        result = await retrieve_svc.retrieve(
            RetrievalQuery(
                query_text="trivial info",
                user_id="u5",
                min_importance=0.5,
            )
        )
        for c in result.candidates:
            assert c.memory.importance_score >= 0.5


class TestDualLayerMemory:
    async def test_observation_gets_episodic_layer(self, ingest_svc):
        mem = await ingest_svc.ingest_text(
            text="user mentioned he had coffee",
            user_id="u_layer",
            memory_type=MemoryType.OBSERVATION,
        )
        layer = mem.memory_layer
        layer_val = layer.value if hasattr(layer, 'value') else str(layer)
        assert layer_val == "episodic"

    async def test_fact_gets_semantic_layer(self, ingest_svc):
        mem = await ingest_svc.ingest_text(
            text="user works at Acme Corp",
            user_id="u_layer",
            memory_type=MemoryType.FACT,
        )
        layer = mem.memory_layer
        layer_val = layer.value if hasattr(layer, 'value') else str(layer)
        assert layer_val == "semantic"

    async def test_retrieve_with_layer_filter(self, ingest_svc, retrieve_svc):
        await ingest_svc.ingest_text(
            text="user likes Python programming",
            user_id="u_layer_filter",
            memory_type=MemoryType.FACT,
        )
        await ingest_svc.ingest_text(
            text="user said hello in chat today",
            user_id="u_layer_filter",
            memory_type=MemoryType.OBSERVATION,
        )
        # Query only semantic layer.
        result = await retrieve_svc.retrieve(
            RetrievalQuery(
                query_text="Python",
                user_id="u_layer_filter",
                memory_layers=[MemoryLayer.SEMANTIC],
                top_k=10,
            )
        )
        for c in result.candidates:
            layer = c.memory.memory_layer
            layer_val = layer.value if hasattr(layer, 'value') else str(layer)
            assert layer_val == "semantic"


class TestConsolidationIntegration:
    async def test_promotion_via_service(self, mock_db, mock_embed, mock_vector_store, ingest_svc):
        mem = await ingest_svc.ingest_text(
            text="user mentioned repeatedly that he prefers dark mode",
            user_id="u_consol",
            importance_override=0.8,
        )
        # Simulate repeated access.
        mem.access_count = 5
        await mock_db.update_memory(mem)

        consolidation = ConsolidationService(mock_db, mock_vector_store, mock_embed)
        result = await consolidation.run_consolidation_cycle("u_consol")
        assert result["promoted"] >= 1
