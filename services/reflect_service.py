"""Reflection service - synthesize high-level insights from raw memories."""
from __future__ import annotations

import logging

from core.exceptions import LLMError
from datetime import datetime, timezone
from typing import Any

from core.schemas.memory import (
    MemoryItem, MemoryType, Reflection, SourceType,
)

logger = logging.getLogger(__name__)


REFLECTION_PROMPT = """You are analyzing a set of memories about a user to generate higher-level insights.

Recent memories:
{memories}

Based on these observations, generate 1-3 high-level reflections or insights about this user.
Each reflection should represent a pattern, preference, or behavioral tendency - NOT just a restatement of individual facts.

Respond with JSON:
{{
  "reflections": [
    {{
      "content": "the reflection statement",
      "confidence": 0.0-1.0,
      "supporting_indices": [0, 1, 2]
    }}
  ]
}}"""


class ReflectionService:
    """Generates reflections (higher-level memory summaries) from raw observations."""

    def __init__(
        self,
        relational_store: Any,
        ingest_service: Any,
        llm_client: Any,
    ) -> None:
        self._db = relational_store
        self._ingest = ingest_service
        self._llm = llm_client

    async def should_reflect(
        self,
        user_id: str,
        namespace: str,
        threshold: int = 10,
    ) -> bool:
        """Check if enough new observations have accumulated to warrant reflection."""
        count = await self._db.count_memories(user_id=user_id, namespace=namespace)
        return count % threshold == 0 and count > 0

    async def generate_reflections(
        self,
        user_id: str,
        namespace: str,
        agent_id: str = "",
        limit: int = 20,
    ) -> list[Reflection]:
        """Generate reflections from recent memories."""
        memories = await self._db.list_memories(
            user_id=user_id,
            namespace=namespace,
            memory_type="observation",
            limit=limit,
        )

        if len(memories) < 3:
            logger.info(f"Not enough memories for reflection: {len(memories)}")
            return []

        memory_texts = [f"- {m.content}" for m in memories]
        memories_str = "\n".join(memory_texts)

        try:
            result = await self._llm.generate_json(
                REFLECTION_PROMPT.format(memories=memories_str)
            )
        except LLMError:
            raise  # LLM unavailable must surface (HTTP 503), never become a default answer
        except Exception as e:
            logger.error(f"Reflection LLM output unusable: {e}")
            return []

        reflections = []
        for ref_data in result.get("reflections", []):
            content = ref_data.get("content", "")
            confidence = ref_data.get("confidence", 0.7)
            supporting_indices = ref_data.get("supporting_indices", [])

            derivation_ids = [
                memories[i].memory_id
                for i in supporting_indices
                if i < len(memories)
            ]

            reflection = Reflection(
                user_id=user_id,
                agent_id=agent_id,
                namespace=namespace,
                content=content,
                derivation_ids=derivation_ids,
                confidence=confidence,
            )
            reflections.append(reflection)

            # Store reflection as a memory item
            await self._ingest.ingest_text(
                text=content,
                user_id=user_id,
                agent_id=agent_id,
                memory_type=MemoryType.REFLECTION,
                source_type=SourceType.REFLECTION,
                metadata={
                    "derivation_ids": derivation_ids,
                    "confidence": confidence,
                    "reflection_id": reflection.reflection_id,
                },
            )

        logger.info(
            f"Generated {len(reflections)} reflections for user={user_id} "
            f"from {len(memories)} memories"
        )
        return reflections

    async def run_reflection_cycle(
        self,
        user_id: str,
        namespace: str,
        agent_id: str = "",
        force: bool = False,
    ) -> list[Reflection]:
        """Run a full reflection cycle if conditions are met."""
        if force or await self.should_reflect(user_id, namespace):
            return await self.generate_reflections(user_id, namespace, agent_id)
        return []
