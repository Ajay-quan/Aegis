"""Memory consolidation service — episodic → semantic promotion and deduplication.

Pipeline:
    1. Scan episodic memories that exceed access/importance thresholds
    2. Promote qualified episodic memories to the semantic layer
    3. Merge near-duplicate semantic memories into consolidated records
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from core.config.settings import settings
from core.schemas.memory import (
    MemoryItem, MemoryLayer, MemoryStatus, MemoryType, SourceType,
)

logger = logging.getLogger(__name__)


class ConsolidationService:
    """Promotes high-value episodic memories to semantic and merges duplicates."""

    def __init__(
        self,
        relational_store: Any,
        vector_store: Any,
        embedding_backend: Any,
        llm_client: Any | None = None,
    ) -> None:
        self._db = relational_store
        self._vs = vector_store
        self._embed = embedding_backend
        self._llm = llm_client

    async def run_consolidation_cycle(
        self, user_id: str, namespace: str = "",
    ) -> dict[str, int]:
        """Full consolidation: promote episodic → semantic, then merge duplicates.

        Returns counts of promotions and merges performed.
        """
        promoted = await self.promote_to_semantic(user_id, namespace)
        merged = await self.merge_similar(user_id, namespace)
        logger.info(
            f"Consolidation for user={user_id}: promoted={promoted}, merged={merged}"
        )
        return {"promoted": promoted, "merged": merged}

    async def promote_to_semantic(
        self, user_id: str, namespace: str = "",
    ) -> int:
        """Promote episodic memories that meet access + importance thresholds.

        Conditions (all must be met):
        - memory_layer == EPISODIC
        - access_count >= consolidation_access_threshold
        - importance_score >= consolidation_importance_threshold
        """
        memories = await self._db.list_memories(
            user_id=user_id, namespace=namespace, status="active",
        )

        promoted_count = 0
        for mem in memories:
            layer = getattr(mem, 'memory_layer', 'episodic')
            layer_val = layer.value if hasattr(layer, 'value') else str(layer)

            if layer_val != "episodic":
                continue
            if mem.access_count < settings.consolidation_access_threshold:
                continue
            if mem.importance_score < settings.consolidation_importance_threshold:
                continue

            # Promote to semantic layer.
            mem.memory_layer = MemoryLayer.SEMANTIC
            mem.updated_at = datetime.now(timezone.utc)
            mem.metadata["promoted_from_episodic"] = True
            mem.metadata["promoted_at"] = datetime.now(timezone.utc).isoformat()

            try:
                await self._db.update_memory(mem)
                # Update vector store payload with new layer.
                if mem.content_embedding:
                    await self._vs.upsert(
                        id=mem.memory_id,
                        vector=mem.content_embedding,
                        payload={
                            "user_id": mem.user_id,
                            "namespace": mem.namespace,
                            "memory_type": mem.memory_type if isinstance(mem.memory_type, str) else mem.memory_type,
                            "memory_layer": "semantic",
                            "content": mem.content[:500],
                            "importance_score": mem.importance_score,
                            "status": "active",
                        },
                    )
                promoted_count += 1
                logger.debug(f"Promoted memory {mem.memory_id} to semantic layer")
            except Exception as e:
                logger.warning(f"Failed to promote memory {mem.memory_id}: {e}")

        return promoted_count

    async def merge_similar(
        self, user_id: str, namespace: str = "",
    ) -> int:
        """Merge near-duplicate semantic memories into consolidated records.

        Uses embedding similarity to find pairs above the merge threshold,
        keeps the higher-importance memory and supersedes the other.
        """
        memories = await self._db.list_memories(
            user_id=user_id, namespace=namespace, status="active",
        )

        # Only consider semantic-layer memories for merging.
        semantic_mems = []
        for m in memories:
            layer = getattr(m, 'memory_layer', 'episodic')
            layer_val = layer.value if hasattr(layer, 'value') else str(layer)
            if layer_val == "semantic":
                semantic_mems.append(m)

        if len(semantic_mems) < 2:
            return 0

        merged_count = 0
        merged_ids: set[str] = set()

        for i, mem_a in enumerate(semantic_mems):
            if mem_a.memory_id in merged_ids:
                continue
            for mem_b in semantic_mems[i + 1:]:
                if mem_b.memory_id in merged_ids:
                    continue

                similarity = await self._compute_similarity(mem_a, mem_b)
                if similarity < settings.consolidation_similarity_threshold:
                    continue

                # Merge: keep the better one, supersede the other.
                if mem_a.importance_score >= mem_b.importance_score:
                    winner, loser = mem_a, mem_b
                else:
                    winner, loser = mem_b, mem_a

                loser.status = MemoryStatus.SUPERSEDED
                loser.metadata["merged_into"] = winner.memory_id
                loser.updated_at = datetime.now(timezone.utc)

                winner.access_count += loser.access_count
                winner.parent_memory_ids.append(loser.memory_id)
                winner.updated_at = datetime.now(timezone.utc)

                try:
                    await self._db.update_memory(winner)
                    await self._db.update_memory(loser)
                    merged_ids.add(loser.memory_id)
                    merged_count += 1
                    logger.debug(
                        f"Merged memory {loser.memory_id} into {winner.memory_id} "
                        f"(sim={similarity:.3f})"
                    )
                except Exception as e:
                    logger.warning(f"Failed to merge memories: {e}")

        return merged_count

    async def _compute_similarity(
        self, mem_a: MemoryItem, mem_b: MemoryItem,
    ) -> float:
        """Compute cosine similarity between two memories."""
        try:
            embeddings = await self._embed.embed([mem_a.content, mem_b.content])
            return self._embed.cosine_similarity(embeddings[0], embeddings[1])
        except Exception:
            return 0.0
