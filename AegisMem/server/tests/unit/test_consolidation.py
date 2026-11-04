"""Unit tests for consolidation service."""
import pytest
import pytest_asyncio
from datetime import datetime, timezone

from core.schemas.memory import MemoryItem, MemoryType, MemoryLayer, MemoryStatus
from services.consolidation_service import ConsolidationService


def make_memory(
    content: str,
    user_id: str = "u1",
    access_count: int = 0,
    importance: float = 0.5,
    layer: MemoryLayer = MemoryLayer.EPISODIC,
    status: MemoryStatus = MemoryStatus.ACTIVE,
) -> MemoryItem:
    return MemoryItem(
        namespace=f"user:{user_id}",
        user_id=user_id,
        memory_type=MemoryType.OBSERVATION,
        memory_layer=layer,
        content=content,
        importance_score=importance,
        access_count=access_count,
        status=status,
    )


class TestConsolidationPromotion:
    async def test_promotes_high_value_episodic(self, mock_db, mock_embed, mock_vector_store):
        svc = ConsolidationService(mock_db, mock_vector_store, mock_embed)

        # Create episodic memory that exceeds both thresholds.
        mem = make_memory("user loves Python", access_count=5, importance=0.8)
        await mock_db.save_memory(mem)

        promoted = await svc.promote_to_semantic("u1")
        assert promoted == 1

        updated = await mock_db.get_memory(mem.memory_id)
        layer = updated.memory_layer
        layer_val = layer.value if hasattr(layer, 'value') else str(layer)
        assert layer_val == "semantic"

    async def test_does_not_promote_low_access(self, mock_db, mock_embed, mock_vector_store):
        svc = ConsolidationService(mock_db, mock_vector_store, mock_embed)

        mem = make_memory("low access fact", access_count=1, importance=0.8)
        await mock_db.save_memory(mem)

        promoted = await svc.promote_to_semantic("u1")
        assert promoted == 0

    async def test_does_not_promote_low_importance(self, mock_db, mock_embed, mock_vector_store):
        svc = ConsolidationService(mock_db, mock_vector_store, mock_embed)

        mem = make_memory("low importance", access_count=10, importance=0.3)
        await mock_db.save_memory(mem)

        promoted = await svc.promote_to_semantic("u1")
        assert promoted == 0

    async def test_does_not_promote_already_semantic(self, mock_db, mock_embed, mock_vector_store):
        svc = ConsolidationService(mock_db, mock_vector_store, mock_embed)

        mem = make_memory("already semantic", access_count=10, importance=0.9, layer=MemoryLayer.SEMANTIC)
        await mock_db.save_memory(mem)

        promoted = await svc.promote_to_semantic("u1")
        assert promoted == 0


class TestConsolidationMerge:
    async def test_merge_identical_memories(self, mock_db, mock_embed, mock_vector_store):
        svc = ConsolidationService(mock_db, mock_vector_store, mock_embed)

        # Two identical semantic memories.
        mem_a = make_memory("user works at Acme Corp", importance=0.9, layer=MemoryLayer.SEMANTIC)
        mem_b = make_memory("user works at Acme Corp", importance=0.7, layer=MemoryLayer.SEMANTIC)
        await mock_db.save_memory(mem_a)
        await mock_db.save_memory(mem_b)

        merged = await svc.merge_similar("u1")
        assert merged >= 1

        # Lower importance memory should be superseded.
        loser = await mock_db.get_memory(mem_b.memory_id)
        status = loser.status if isinstance(loser.status, str) else loser.status
        assert status in ("superseded", MemoryStatus.SUPERSEDED)

    async def test_no_merge_for_different_content(self, mock_db, mock_embed, mock_vector_store):
        svc = ConsolidationService(mock_db, mock_vector_store, mock_embed)

        mem_a = make_memory("user likes Python", importance=0.8, layer=MemoryLayer.SEMANTIC)
        mem_b = make_memory("user has a golden retriever", importance=0.7, layer=MemoryLayer.SEMANTIC)
        await mock_db.save_memory(mem_a)
        await mock_db.save_memory(mem_b)

        merged = await svc.merge_similar("u1")
        assert merged == 0


class TestConsolidationCycle:
    async def test_full_cycle_returns_counts(self, mock_db, mock_embed, mock_vector_store):
        svc = ConsolidationService(mock_db, mock_vector_store, mock_embed)

        mem = make_memory("promotable memory", access_count=10, importance=0.9)
        await mock_db.save_memory(mem)

        result = await svc.run_consolidation_cycle("u1")
        assert "promoted" in result
        assert "merged" in result
        assert isinstance(result["promoted"], int)
        assert isinstance(result["merged"], int)
