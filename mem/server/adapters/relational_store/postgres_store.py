"""PostgreSQL async relational store using SQLAlchemy 2.x."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy import select, update, and_, func, delete, or_

from core.exceptions import MemoryNotFoundError, MemoryStorageError
from core.tenancy_context import apply_rls
from .pg_utils import ensure_pgvector
from core.schemas.memory import MemoryItem, MemoryStatus, FactRecord as SchemaFact
from .models import (
    Base, MemoryRecord, FactRecord as DBFact, ReflectionRecord,
    ContradictionRecord, MemoryOperationLog, EvaluationResult,
)

logger = logging.getLogger(__name__)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _enum(v: Any) -> str:
    return v if isinstance(v, str) else v.value


class PostgresStore:
    """Async PostgreSQL store for canonical memory records."""

    def __init__(self, database_url: str) -> None:
        self._engine = create_async_engine(
            database_url,
            pool_pre_ping=True,
            pool_size=10,
            max_overflow=20,
            echo=False,
        )
        self._session_factory = async_sessionmaker(
            self._engine, expire_on_commit=False
        )

    async def initialize(self) -> None:
        """Create all tables."""
        async with self._engine.begin() as conn:
            await ensure_pgvector(conn)
            await conn.run_sync(Base.metadata.create_all)
        logger.info("PostgreSQL schema initialized")

    @asynccontextmanager
    async def session(self) -> AsyncGenerator[AsyncSession, None]:
        async with self._session_factory() as sess:
            try:
                await apply_rls(sess)
                yield sess
                await sess.commit()
            except Exception:
                await sess.rollback()
                raise

    # ------------------------------------------------------------------
    # Memory CRUD
    # ------------------------------------------------------------------

    async def save_memory(self, memory: MemoryItem) -> MemoryItem:
        async with self.session() as sess:
            record = MemoryRecord(
                memory_id=memory.memory_id,
                tenant_id=memory.tenant_id,
                memory_layer=_enum(memory.memory_layer),
                retrieval_count=memory.retrieval_count,
                successful_retrieval_count=memory.successful_retrieval_count,
                contradicted_by=memory.contradicted_by,
                namespace=memory.namespace,
                user_id=memory.user_id,
                agent_id=memory.agent_id,
                memory_type=memory.memory_type if isinstance(memory.memory_type, str) else memory.memory_type.value,
                content=memory.content,
                source_type=memory.source_type if isinstance(memory.source_type, str) else memory.source_type.value,
                source_ref=memory.source_ref,
                created_at=memory.created_at,
                updated_at=memory.updated_at,
                event_time=memory.event_time,
                valid_from=memory.valid_from,
                valid_to=memory.valid_to,
                importance_score=memory.importance_score,
                recency_score=memory.recency_score,
                confidence_score=memory.confidence_score,
                access_count=memory.access_count,
                version=memory.version,
                status=memory.status if isinstance(memory.status, str) else memory.status.value,
                contradiction_status=memory.contradiction_status if isinstance(memory.contradiction_status, str) else memory.contradiction_status.value,
                parent_memory_ids=memory.parent_memory_ids,
                tags=memory.tags,
                extra_metadata=memory.metadata,
            )
            sess.add(record)
            await self._log_operation(sess, memory.memory_id, memory.user_id, "create", {})
        return memory

    async def get_memory(self, memory_id: str) -> MemoryItem:
        async with self.session() as sess:
            result = await sess.get(MemoryRecord, memory_id)
            if not result:
                raise MemoryNotFoundError(memory_id)
            return self._record_to_schema(result)

    async def update_memory(self, memory: MemoryItem) -> MemoryItem:
        async with self.session() as sess:
            record = await sess.get(MemoryRecord, memory.memory_id)
            if not record:
                raise MemoryNotFoundError(memory.memory_id)
            # Persist every mutable field; anything omitted here is silently lost on reload.
            record.content = memory.content
            record.updated_at = utcnow()
            record.status = _enum(memory.status)
            record.memory_layer = _enum(memory.memory_layer)
            record.importance_score = memory.importance_score
            record.confidence_score = memory.confidence_score
            record.access_count = memory.access_count
            record.retrieval_count = memory.retrieval_count
            record.successful_retrieval_count = memory.successful_retrieval_count
            record.version = memory.version
            record.contradiction_status = _enum(memory.contradiction_status)
            record.contradicted_by = list(memory.contradicted_by)
            record.parent_memory_ids = list(memory.parent_memory_ids)
            record.valid_from = memory.valid_from
            record.valid_to = memory.valid_to
            record.tags = list(memory.tags)
            record.extra_metadata = dict(memory.metadata)
            await self._log_operation(sess, memory.memory_id, memory.user_id, "update", {})
        return memory

    async def delete_memory(self, memory_id: str, user_id: str) -> None:
        async with self.session() as sess:
            record = await sess.get(MemoryRecord, memory_id)
            if record:
                record.status = "deleted"
                record.updated_at = utcnow()
                await self._log_operation(sess, memory_id, user_id, "delete", {})

    async def purge_memory(self, memory_id: str, user_id: str) -> None:
        """Hard delete: removes the row and any contradiction text that may quote it.

        Unlike ``delete_memory`` (a soft status flag), nothing recoverable remains.
        The operation log keeps a content-free ``purge`` entry for accountability.
        """
        async with self.session() as sess:
            await sess.execute(delete(MemoryRecord).where(MemoryRecord.memory_id == memory_id))
            await sess.execute(delete(ContradictionRecord).where(or_(
                ContradictionRecord.memory_a_id == memory_id,
                ContradictionRecord.memory_b_id == memory_id,
            )))
            await self._log_operation(sess, memory_id, user_id, "purge", {})

    async def list_memories(
        self,
        user_id: str,
        namespace: str = "",
        tenant_id: str | None = None,
        memory_type: str = "",
        status: str = "active",
        limit: int = 50,
        offset: int = 0,
    ) -> list[MemoryItem]:
        async with self.session() as sess:
            stmt = select(MemoryRecord).where(MemoryRecord.user_id == user_id)
            if tenant_id is not None:
                stmt = stmt.where(MemoryRecord.tenant_id == tenant_id)
            if namespace:
                stmt = stmt.where(MemoryRecord.namespace == namespace)
            if memory_type:
                stmt = stmt.where(MemoryRecord.memory_type == memory_type)
            if status:
                stmt = stmt.where(MemoryRecord.status == status)
            stmt = stmt.order_by(MemoryRecord.created_at.desc()).limit(limit).offset(offset)
            result = await sess.execute(stmt)
            records = result.scalars().all()
            return [self._record_to_schema(r) for r in records]

    async def count_memories(
        self, user_id: str, namespace: str = "", tenant_id: str | None = None,
    ) -> int:
        async with self.session() as sess:
            stmt = select(func.count()).select_from(MemoryRecord).where(
                MemoryRecord.user_id == user_id,
                MemoryRecord.status == "active",
            )
            if tenant_id is not None:
                stmt = stmt.where(MemoryRecord.tenant_id == tenant_id)
            if namespace:
                stmt = stmt.where(MemoryRecord.namespace == namespace)
            result = await sess.execute(stmt)
            return result.scalar() or 0

    # ------------------------------------------------------------------
    # Facts CRUD
    # ------------------------------------------------------------------

    async def save_fact(self, fact: SchemaFact) -> SchemaFact:
        async with self.session() as sess:
            record = DBFact(
                fact_id=fact.fact_id,
                user_id=fact.user_id,
                agent_id=fact.agent_id,
                namespace=fact.namespace,
                subject=fact.subject,
                predicate=fact.predicate,
                object=fact.obj,
                confidence=fact.confidence,
                source_memory_ids=fact.source_memory_ids,
                valid_from=fact.valid_from,
                valid_to=fact.valid_to,
                created_at=fact.created_at,
                updated_at=fact.updated_at,
                status=fact.status if isinstance(fact.status, str) else fact.status.value,
            )
            sess.add(record)
        return fact

    async def get_facts_for_user(self, user_id: str, subject: str = "") -> list[dict[str, Any]]:
        async with self.session() as sess:
            stmt = select(DBFact).where(DBFact.user_id == user_id, DBFact.status == "active")
            if subject:
                stmt = stmt.where(DBFact.subject == subject)
            result = await sess.execute(stmt)
            rows = result.scalars().all()
            return [
                {
                    "fact_id": r.fact_id,
                    "subject": r.subject,
                    "predicate": r.predicate,
                    "object": r.object,
                    "confidence": r.confidence,
                }
                for r in rows
            ]

    # ------------------------------------------------------------------
    # Contradiction CRUD
    # ------------------------------------------------------------------

    async def save_contradiction(self, report_id: str, a_id: str, b_id: str,
                                 description: str, confidence: float) -> None:
        async with self.session() as sess:
            record = ContradictionRecord(
                report_id=report_id,
                memory_a_id=a_id,
                memory_b_id=b_id,
                contradiction_description=description,
                confidence=confidence,
            )
            sess.add(record)

    async def list_contradictions(self, resolved: bool = False) -> list[dict[str, Any]]:
        async with self.session() as sess:
            stmt = select(ContradictionRecord).where(ContradictionRecord.resolved == resolved)
            result = await sess.execute(stmt)
            rows = result.scalars().all()
            return [
                {
                    "report_id": r.report_id,
                    "memory_a_id": r.memory_a_id,
                    "memory_b_id": r.memory_b_id,
                    "description": r.contradiction_description,
                    "confidence": r.confidence,
                    "detected_at": r.detected_at.isoformat(),
                }
                for r in rows
            ]

    # ------------------------------------------------------------------
    # Operation log
    # ------------------------------------------------------------------

    async def _log_operation(
        self,
        session: AsyncSession,
        memory_id: str,
        user_id: str,
        operation: str,
        details: dict[str, Any],
    ) -> None:
        log = MemoryOperationLog(
            memory_id=memory_id,
            user_id=user_id,
            operation=operation,
            details=details,
        )
        session.add(log)

    async def get_operation_logs(self, memory_id: str) -> list[dict[str, Any]]:
        async with self.session() as sess:
            stmt = select(MemoryOperationLog).where(
                MemoryOperationLog.memory_id == memory_id
            ).order_by(MemoryOperationLog.created_at)
            result = await sess.execute(stmt)
            rows = result.scalars().all()
            return [
                {"operation": r.operation, "at": r.created_at.isoformat(), "details": r.details}
                for r in rows
            ]

    # ------------------------------------------------------------------
    # Evaluation results
    # ------------------------------------------------------------------

    async def save_eval_result(
        self, eval_name: str, run_id: str, metrics: dict[str, Any], config: dict[str, Any]
    ) -> None:
        async with self.session() as sess:
            record = EvaluationResult(
                eval_name=eval_name,
                run_id=run_id,
                metrics=metrics,
                config=config,
            )
            sess.add(record)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _record_to_schema(self, record: MemoryRecord) -> MemoryItem:
        from core.schemas.memory import MemoryType, MemoryStatus, SourceType, ContradictionStatus
        return MemoryItem(
            memory_id=record.memory_id,
            tenant_id=record.tenant_id,
            memory_layer=record.memory_layer,
            retrieval_count=record.retrieval_count or 0,
            successful_retrieval_count=record.successful_retrieval_count or 0,
            contradicted_by=record.contradicted_by or [],
            namespace=record.namespace,
            user_id=record.user_id,
            agent_id=record.agent_id,
            memory_type=record.memory_type,
            content=record.content,
            source_type=record.source_type,
            source_ref=record.source_ref,
            created_at=record.created_at,
            updated_at=record.updated_at,
            event_time=record.event_time,
            valid_from=record.valid_from,
            valid_to=record.valid_to,
            importance_score=record.importance_score,
            recency_score=record.recency_score,
            confidence_score=record.confidence_score,
            access_count=record.access_count,
            version=record.version,
            status=record.status,
            contradiction_status=record.contradiction_status,
            parent_memory_ids=record.parent_memory_ids or [],
            tags=record.tags or [],
            metadata=record.extra_metadata or {},
        )

    async def rls_effective(self) -> tuple[bool, str]:
        """RLS is meaningless if the connecting role is a superuser or has BYPASSRLS."""
        if self._engine.dialect.name != "postgresql":
            return True, "not postgres"
        async with self._engine.connect() as conn:
            row = (await conn.exec_driver_sql(
                "SELECT rolsuper, rolbypassrls, current_user FROM pg_roles WHERE rolname = current_user"
            )).first()
        if row is None:
            return False, "cannot inspect current role"
        if row[0] or row[1]:
            return False, f"role '{row[2]}' is superuser or BYPASSRLS"
        return True, f"role '{row[2]}'"

    async def ping(self) -> None:
        async with self._engine.connect() as conn:
            await conn.exec_driver_sql("SELECT 1")

    async def close(self) -> None:
        await self._engine.dispose()
