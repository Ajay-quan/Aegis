"""Memory ingestion service - process observations into stored memories."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from core.schemas.memory import (
    MemoryItem, MemoryType, MemoryLayer, SourceType, Observation, MemoryStatus,
)
from domain.integrity.provenance import (
    base_trust, derived_from, derived_trust, get_trust, should_quarantine,
)
from core.config.settings import settings
from core.observability.metrics import WRITES
from domain.privacy.redaction import redact
from opentelemetry import trace
from core.observability.tracing import tracer
from services.vector_sync import index_payload
from domain.memory.scoring import compute_importance_heuristic

logger = logging.getLogger(__name__)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class IngestionService:
    """Processes raw observations into structured MemoryItems."""

    def __init__(
        self,
        relational_store: Any,
        vector_store: Any,
        embedding_backend: Any,
        graph_store: Any | None = None,
        llm_client: Any | None = None,
        trust_calibrator: Any | None = None,
        risk_model: Any | None = None,
    ) -> None:
        self._db = relational_store
        self._vs = vector_store
        self._embed = embedding_backend
        self._graph = graph_store
        self._llm = llm_client
        self._calibrator = trust_calibrator
        self._risk = risk_model

    async def ingest_observation(
        self,
        observation: Observation,
        memory_type: MemoryType = MemoryType.OBSERVATION,
        importance_override: float | None = None,
    ) -> MemoryItem:
        """Convert an observation into a stored memory (span: aegis.ingest)."""
        with tracer.start_as_current_span("aegis.ingest"):
            return await self._ingest_observation(observation, memory_type, importance_override)

    async def _ingest_observation(
        self,
        observation: Observation,
        memory_type: MemoryType = MemoryType.OBSERVATION,
        importance_override: float | None = None,
    ) -> MemoryItem:
        pii: dict[str, Any] = {}
        if settings.pii_redaction_enabled:
            # Redact at the boundary, before screening and embedding: raw PII is never
            # embedded, indexed, scored or retrievable.
            result = redact(observation.content)
            if result.redacted:
                observation = observation.model_copy(update={"content": result.text})
                pii = {"pii_redacted": True, "pii_counts": result.counts}
                logger.info(f"Redacted {result.total} PII token(s) at ingest: {result.counts}")
        importance = importance_override or compute_importance_heuristic(observation.content)
        metadata, status = await self._provenance(observation)
        metadata.update(pii)

        memory = MemoryItem(
            namespace=f"user:{observation.user_id}",
            user_id=observation.user_id,
            agent_id=observation.agent_id,
            memory_type=memory_type,
            memory_layer=self._classify_layer(memory_type),
            content=observation.content,
            source_type=observation.source_type,
            source_ref=observation.session_id,
            event_time=observation.observed_at,
            importance_score=importance,
            metadata=metadata,
            status=status,
        )

        # Save to relational store
        await self._db.save_memory(memory)

        # Embed and index. The canonical row is already saved; if indexing fails the
        # memory is queued for repair (outbox) instead of becoming silently unretrievable.
        try:
            embedding = await self._embed.embed_single(observation.content)
            memory.content_embedding = embedding
            await self._vs.upsert(id=memory.memory_id, vector=embedding, payload=index_payload(memory))
        except Exception as e:
            logger.warning(f"Indexing failed for memory {memory.memory_id}: {e}")
            enqueue = getattr(self._vs, "enqueue_upsert", None)
            if enqueue is None:
                raise
            await enqueue(memory.memory_id)

        # Create graph node
        if self._graph and self._graph.is_available():
            try:
                await self._graph.create_memory_node(
                    memory.memory_id,
                    {
                        "tenant_id": memory.tenant_id,
                        "user_id": memory.user_id,
                        "memory_type": memory.memory_type,
                        "importance": memory.importance_score,
                    },
                )
            except Exception as e:
                logger.warning(f"Graph node creation failed: {e}")

        logger.info(
            f"Ingested memory {memory.memory_id} for user {memory.user_id} "
            f"(type={memory.memory_type}, importance={importance:.2f})"
        )
        return memory

    async def _provenance(self, observation: Observation) -> tuple[dict[str, Any], MemoryStatus]:
        """Attach provenance + trust; quarantine low-trust instruction-like content."""
        metadata = dict(observation.metadata)
        prov = dict(metadata.get("provenance") or {})
        source = observation.source_type.value if hasattr(observation.source_type, "value") \
            else str(observation.source_type)
        origin = str(prov.get("origin") or metadata.get("origin") or "")
        if self._calibrator is not None:
            trust = await self._calibrator.trust(source, origin)  # learned from outcomes
        else:
            trust = base_trust(observation.source_type)
        if "trust" in prov:  # callers may lower trust, never raise it above the source default
            trust = min(trust, float(prov["trust"]))

        upstream = derived_from(metadata)
        source_trusts = []
        for mid in upstream:
            try:
                source_trusts.append(get_trust((await self._db.get_memory(mid)).metadata))
            except Exception:
                source_trusts.append(0.0)  # unknown source: assume untrusted
        trust = derived_trust(trust, source_trusts)

        prov.update({
            "source": source,
            "origin": origin,
            "trust": round(trust, 3),
            "origin_ref": prov.get("origin_ref") or observation.session_id,
            "derived_from": upstream,
        })
        metadata["provenance"] = prov

        status = MemoryStatus.ACTIVE
        quarantine: dict[str, Any] | None = None
        reason = should_quarantine(observation.content, trust)
        if reason:
            quarantine = {"trigger": "rule", "reason": reason}
        if self._risk is not None:
            risk = self._risk.score(observation.content, trust)
            metadata["risk"] = {"p": risk.probability, "threshold": risk.threshold}
            if quarantine is None and risk.flagged:
                reason = (
                    f"learned risk {risk.probability:.2f} >= {risk.threshold:.2f} "
                    f"(signals: {', '.join(risk.top_features) or 'n/a'})"
                )
                quarantine = {"trigger": "model", "reason": reason, "features": risk.top_features}
        if quarantine:
            status = MemoryStatus.PENDING
            quarantine["at"] = utcnow().isoformat()
            metadata["quarantine"] = quarantine
            logger.warning(f"Quarantined memory from session={observation.session_id}: {reason}")
        outcome = f"quarantined_{quarantine['trigger']}" if quarantine else "stored"
        WRITES.labels(getattr(self._db, "tenant_id", "unscoped"), source, outcome).inc()
        trace.get_current_span().set_attributes({
            "aegis.write.source": source, "aegis.write.outcome": outcome,
            "aegis.write.trust": round(trust, 3)})
        return metadata, status

    async def ingest_batch(
        self,
        observations: list[Observation],
    ) -> list[MemoryItem]:
        """Batch ingest multiple observations."""
        memories = []
        for obs in observations:
            try:
                mem = await self.ingest_observation(obs)
                memories.append(mem)
            except Exception as e:
                logger.error(f"Failed to ingest observation {obs.observation_id}: {e}")
        return memories

    async def ingest_text(
        self,
        text: str,
        user_id: str,
        session_id: str = "",
        agent_id: str = "",
        memory_type: MemoryType = MemoryType.OBSERVATION,
        source_type: SourceType = SourceType.USER_MESSAGE,
        metadata: dict[str, Any] | None = None,
        importance_override: float | None = None,
        event_time: datetime | None = None,
    ) -> MemoryItem:
        """Convenience method to ingest plain text."""
        obs = Observation(
            **({"observed_at": event_time} if event_time else {}),
            session_id=session_id,
            user_id=user_id,
            agent_id=agent_id,
            content=text,
            source_type=source_type,
            metadata=metadata or {},
        )
        return await self.ingest_observation(obs, memory_type=memory_type, importance_override=importance_override)

    @staticmethod
    def _classify_layer(memory_type: MemoryType) -> MemoryLayer:
        """Auto-classify memory layer based on type."""
        semantic_types = {
            MemoryType.FACT, MemoryType.PROCEDURE,
            MemoryType.REFLECTION, MemoryType.SUMMARY,
        }
        mt = memory_type if isinstance(memory_type, MemoryType) else MemoryType(memory_type)
        return MemoryLayer.SEMANTIC if mt in semantic_types else MemoryLayer.EPISODIC
