"""Contradiction detection and resolution service.

Uses LLM to classify the relationship between two memories into:
  - direct_conflict: mutually exclusive assertions
  - preference_change: updated user preference
  - temporal_update: newer fact supersedes older
  - none: no contradiction
"""
from __future__ import annotations

import json
import logging

from core.exceptions import LLMError
import uuid
from datetime import datetime, timezone
from typing import Any

from core.config.settings import settings
from core.schemas.memory import (
    MemoryItem, ContradictionReport, ContradictionStatus,
    ContradictionType, MemoryStatus,
)

logger = logging.getLogger(__name__)


CONTRADICTION_PROMPT = """You are analyzing two memory items for contradictions.

Memory A (created earlier):
{memory_a}

Memory B (created later):
{memory_b}

Classify the relationship. A contradiction means they assert conflicting facts
about the same subject, or the newer memory supersedes the older one.

You MUST respond with valid JSON only — no extra text:
{{
  "contradicts": true or false,
  "confidence": 0.0 to 1.0,
  "contradiction_type": "direct_conflict" | "preference_change" | "temporal_update" | "none",
  "description": "one-sentence explanation",
  "resolution_suggestion": "which memory is more likely current and why"
}}

Rules:
- "direct_conflict": memories make mutually exclusive claims (e.g. lives in X vs. lives in Y)
- "preference_change": user's preference or opinion has changed over time
- "temporal_update": newer memory updates a fact that was once true
- "none": memories are compatible, even if semantically similar
- Buying a gift for someone else does NOT contradict a personal preference
- Temporary actions do NOT contradict general preferences
- Liking multiple things is NOT a contradiction"""


class ContradictionService:
    """Detects and manages contradictions between memories."""

    def __init__(
        self,
        relational_store: Any,
        vector_store: Any,
        embedding_backend: Any,
        llm_client: Any,
        graph_store: Any | None = None,
    ) -> None:
        self._db = relational_store
        self._vs = vector_store
        self._embed = embedding_backend
        self._llm = llm_client
        self._graph = graph_store

    async def check_contradiction(
        self,
        memory_a: MemoryItem,
        memory_b: MemoryItem,
    ) -> ContradictionReport | None:
        """Use LLM to check if two memories contradict each other."""
        prompt = CONTRADICTION_PROMPT.format(
            memory_a=memory_a.content,
            memory_b=memory_b.content,
        )
        try:
            result = await self._llm.generate_json(prompt)
            if result.get("contradicts", False):
                # Parse contradiction type safely.
                raw_type = result.get("contradiction_type", "none")
                try:
                    ctype = ContradictionType(raw_type)
                except ValueError:
                    ctype = ContradictionType.DIRECT_CONFLICT

                report = ContradictionReport(
                    report_id=str(uuid.uuid4()),
                    memory_a_id=memory_a.memory_id,
                    memory_b_id=memory_b.memory_id,
                    contradiction_description=result.get("description", ""),
                    contradiction_type=ctype,
                    confidence=result.get("confidence", 0.5),
                )
                logger.info(
                    f"Contradiction detected: {memory_a.memory_id} vs {memory_b.memory_id} "
                    f"(type={ctype.value}, confidence={report.confidence:.2f})"
                )
                return report
        except LLMError:
            raise  # LLM unavailable must surface (HTTP 503), never become a default answer
        except Exception as e:
            logger.warning(f"Contradiction check failed (unusable model output): {e}")
        return None

    async def scan_for_contradictions(
        self,
        memory: MemoryItem,
        top_k: int = 5,
    ) -> list[ContradictionReport]:
        """Scan existing memories for contradictions with a new memory."""
        reports = []
        try:
            # Find semantically similar memories (potential contradictions).
            embedding = await self._embed.embed_single(memory.content)
            similar = await self._vs.search(
                query_vector=embedding,
                top_k=top_k,
                filter={"user_id": memory.user_id, "status": "active"},
            )

            for hit in similar:
                if hit.id == memory.memory_id:
                    continue
                if hit.score < 0.7:  # only check highly similar memories
                    continue
                try:
                    other = await self._db.get_memory(hit.id)
                    report = await self.check_contradiction(memory, other)
                    if report:
                        reports.append(report)
                        await self._persist_contradiction(memory, other, report)
                except LLMError:
                    raise
                except Exception as e:
                    logger.debug(f"Error checking memory {hit.id}: {e}")

        except LLMError:
            raise  # LLM unavailable must surface (HTTP 503), never become a default answer
        except Exception as e:
            logger.warning(f"Contradiction scan failed: {e}")

        return reports

    async def _persist_contradiction(
        self,
        memory_a: MemoryItem,
        memory_b: MemoryItem,
        report: ContradictionReport,
    ) -> None:
        """Mark both memories and link them via contradicted_by."""
        # Only apply strong status changes if confidence exceeds threshold.
        if report.confidence >= settings.contradiction_confidence_threshold:
            memory_a.contradiction_status = ContradictionStatus.CONFIRMED
            memory_b.contradiction_status = ContradictionStatus.CONFIRMED

            # Link memories bidirectionally.
            if memory_b.memory_id not in memory_a.contradicted_by:
                memory_a.contradicted_by.append(memory_b.memory_id)
            if memory_a.memory_id not in memory_b.contradicted_by:
                memory_b.contradicted_by.append(memory_a.memory_id)

            # Store contradiction confidence in metadata for scoring.
            memory_a.metadata["contradiction_confidence"] = report.confidence
            memory_b.metadata["contradiction_confidence"] = report.confidence

            # For temporal updates, supersede the older memory.
            if report.contradiction_type == ContradictionType.TEMPORAL_UPDATE:
                if memory_a.created_at <= memory_b.created_at:
                    memory_a.status = MemoryStatus.SUPERSEDED
                    memory_a.metadata["superseded_by"] = memory_b.memory_id
                else:
                    memory_b.status = MemoryStatus.SUPERSEDED
                    memory_b.metadata["superseded_by"] = memory_a.memory_id
        else:
            memory_a.contradiction_status = ContradictionStatus.SUSPECTED
            memory_b.contradiction_status = ContradictionStatus.SUSPECTED

        try:
            await self._db.update_memory(memory_a)
            await self._db.update_memory(memory_b)
            await self._db.save_contradiction(
                report_id=report.report_id,
                a_id=report.memory_a_id,
                b_id=report.memory_b_id,
                description=report.contradiction_description,
                confidence=report.confidence,
            )
        except Exception as e:
            logger.error(f"Failed to persist contradiction: {e}")

        # Mark in graph.
        if self._graph and self._graph.is_available():
            try:
                await self._graph.mark_contradiction(
                    memory_a.memory_id, memory_b.memory_id,
                )
            except Exception:
                pass

    async def resolve_contradiction(
        self,
        report_id: str,
        winning_memory_id: str,
        resolution_note: str = "",
    ) -> None:
        """Resolve a contradiction by marking one memory as superseded."""
        logger.info(f"Resolving contradiction {report_id}, keeping {winning_memory_id}")
