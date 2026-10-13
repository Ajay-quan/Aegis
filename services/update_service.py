"""Memory update service - versioned, governed updates."""
from __future__ import annotations

import logging

from core.exceptions import LLMError
from datetime import datetime, timezone
from typing import Any

from core.schemas.memory import MemoryItem, MemoryStatus, MemoryUpdateDecision

logger = logging.getLogger(__name__)


UPDATE_PROMPT = """Given an existing memory and new information, decide what to do.

Existing memory:
{existing}

New information:
{new_info}

Options:
- "update": new info refines/corrects the existing memory
- "merge": both are valid and should be combined
- "supersede": new info completely replaces old
- "skip": new info is redundant, no change needed
- "create": new info is different enough to be a separate memory

Respond with JSON:
{{
  "action": "update|merge|supersede|skip|create",
  "reason": "explanation",
  "merged_content": "if action is merge or update, the combined content",
  "confidence": 0.0-1.0
}}"""


class UpdateService:
    """Handles versioned, governed memory updates."""

    def __init__(
        self,
        relational_store: Any,
        vector_store: Any,
        embedding_backend: Any,
        llm_client: Any,
        ingest_service: Any,
    ) -> None:
        self._db = relational_store
        self._vs = vector_store
        self._embed = embedding_backend
        self._llm = llm_client
        self._ingest = ingest_service

    async def update_or_create(
        self,
        user_id: str,
        new_content: str,
        namespace: str = "",
        agent_id: str = "",
    ) -> tuple[MemoryItem, MemoryUpdateDecision]:
        """Decide whether to create, update, or merge a memory."""
        namespace = namespace or f"user:{user_id}"

        # Find most similar existing memory
        try:
            embedding = await self._embed.embed_single(new_content)
            similar = await self._vs.search(
                query_vector=embedding,
                top_k=1,
                filter={"user_id": user_id, "status": "active"},
            )
        except Exception:
            similar = []

        if not similar or similar[0].score < 0.80:
            # No close match - create new memory
            memory = await self._ingest.ingest_text(
                text=new_content,
                user_id=user_id,
                agent_id=agent_id,
            )
            decision = MemoryUpdateDecision(
                existing_memory_id="",
                new_content=new_content,
                action="create",
                reason="No similar memory found",
                confidence=1.0,
                applied=True,
            )
            return memory, decision

        # Found similar - ask LLM what to do
        existing_id = similar[0].id
        try:
            existing = await self._db.get_memory(existing_id)
        except Exception:
            # Existing not found in DB, create new
            memory = await self._ingest.ingest_text(text=new_content, user_id=user_id)
            decision = MemoryUpdateDecision(
                existing_memory_id=existing_id,
                new_content=new_content,
                action="create",
                reason="Existing memory not found in DB",
                applied=True,
            )
            return memory, decision

        try:
            result = await self._llm.generate_json(
                UPDATE_PROMPT.format(
                    existing=existing.content,
                    new_info=new_content,
                )
            )
            action = result.get("action", "skip")
            reason = result.get("reason", "")
            merged_content = result.get("merged_content", "")
            confidence = result.get("confidence", 0.8)
        except LLMError:
            raise  # LLM unavailable must surface (HTTP 503), never become a default answer
        except Exception as e:
            logger.warning(f"Update LLM output unusable: {e}, defaulting to create")
            action = "create"
            reason = "LLM unavailable"
            merged_content = ""
            confidence = 0.5

        decision = MemoryUpdateDecision(
            existing_memory_id=existing_id,
            new_content=new_content,
            action=action,
            reason=reason,
            confidence=confidence,
        )

        if action == "skip":
            decision.applied = True
            return existing, decision

        elif action == "create":
            memory = await self._ingest.ingest_text(text=new_content, user_id=user_id)
            decision.applied = True
            return memory, decision

        elif action in ("update", "supersede", "merge"):
            # Create new version
            new_version_content = merged_content or new_content
            new_memory = MemoryItem(
                namespace=existing.namespace,
                user_id=existing.user_id,
                agent_id=existing.agent_id,
                memory_type=existing.memory_type,
                content=new_version_content,
                source_type=existing.source_type,
                importance_score=existing.importance_score,
                version=existing.version + 1,
                parent_memory_ids=[existing.memory_id] + existing.parent_memory_ids,
            )

            # Supersede old memory, and keep the index in sync so it stops matching.
            existing.supersede()
            await self._db.update_memory(existing)
            try:
                await self._vs.update_payload(existing.memory_id, {"status": "superseded"})
            except Exception as e:
                logger.warning(f"Vector status sync failed for {existing.memory_id}: {e}")

            # Save new version
            await self._db.save_memory(new_memory)

            # Re-embed new version
            try:
                new_embed = await self._embed.embed_single(new_version_content)
                await self._vs.upsert(
                    id=new_memory.memory_id,
                    vector=new_embed,
                    payload={
                        "user_id": new_memory.user_id,
                        "namespace": new_memory.namespace,
                        "memory_type": new_memory.memory_type,
                        "content": new_version_content[:500],
                        "importance_score": new_memory.importance_score,
                        "status": "active",
                    },
                )
                # Remove old from vector store
                await self._vs.delete(existing_id)
            except Exception as e:
                logger.warning(f"Vector update failed: {e}")

            decision.applied = True
            logger.info(
                f"Memory {action}: {existing_id} -> {new_memory.memory_id} "
                f"(v{existing.version} -> v{new_memory.version})"
            )
            return new_memory, decision

        # Fallback
        decision.applied = False
        return existing, decision
