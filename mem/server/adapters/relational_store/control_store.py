"""Async SQL repository for control-plane state (works on Postgres and SQLite)."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from sqlalchemy.exc import IntegrityError

from .control_models import (
    AuditEvent, IdempotencyRecord, OutboxRecord,
    ApiKeyRecord, ErasureReceiptRecord, LearningEvent, LearningSnapshot, RetrievalLedgerRecord,
)
from .models import Base
from .pg_utils import ensure_pgvector

logger = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(timezone.utc)


class ControlStore:
    def __init__(self, database_url: str | None = None, engine: AsyncEngine | None = None) -> None:
        if engine is None:
            if not database_url:
                raise ValueError("database_url or engine required")
            kwargs: dict[str, Any] = {"pool_pre_ping": True}
            if not database_url.startswith("sqlite"):
                kwargs.update(pool_size=10, max_overflow=20)
            engine = create_async_engine(database_url, **kwargs)
        self._engine = engine
        self._sessions = async_sessionmaker(engine, expire_on_commit=False)
        # SQLite has no row locks; it is a single-process dev backend, so serialize claims.
        self._claim_lock = asyncio.Lock()

    async def create_schema(self) -> None:
        """Dev/test only. Production schema is managed by Alembic migrations."""
        async with self._engine.begin() as conn:
            await ensure_pgvector(conn)
            await conn.run_sync(Base.metadata.create_all)

    async def ping(self) -> None:
        async with self._engine.connect() as conn:
            await conn.exec_driver_sql("SELECT 1")

    async def close(self) -> None:
        await self._engine.dispose()

    # ------------------------------------------------------------------
    # Learning event log + snapshots
    # ------------------------------------------------------------------

    async def append_event(
        self, tenant_id: str, component: str, event: dict[str, Any], actor: str = "",
    ) -> int:
        async with self._sessions.begin() as s:
            rec = LearningEvent(tenant_id=tenant_id, component=component, event=event, actor=actor)
            s.add(rec)
            await s.flush()
            return int(rec.seq)

    async def events_after(
        self, tenant_id: str, component: str, after_seq: int, limit: int = 10_000,
    ) -> list[tuple[int, dict[str, Any]]]:
        async with self._sessions() as s:
            rows = await s.execute(
                select(LearningEvent.seq, LearningEvent.event)
                .where(LearningEvent.tenant_id == tenant_id,
                       LearningEvent.component == component,
                       LearningEvent.seq > after_seq)
                .order_by(LearningEvent.seq)
                .limit(limit)
            )
            return [(int(seq), ev) for seq, ev in rows.all()]

    async def count_events(self, tenant_id: str, component: str) -> int:
        async with self._sessions() as s:
            return int((await s.execute(
                select(func.count()).select_from(LearningEvent)
                .where(LearningEvent.tenant_id == tenant_id, LearningEvent.component == component)
            )).scalar() or 0)

    async def load_snapshot(self, tenant_id: str, component: str) -> tuple[int, dict[str, Any]] | None:
        async with self._sessions() as s:
            rec = await s.get(LearningSnapshot, (tenant_id, component))
            return (int(rec.seq), rec.state) if rec else None

    async def save_snapshot(
        self, tenant_id: str, component: str, seq: int, state: dict[str, Any],
    ) -> None:
        """Upsert; never moves a snapshot backwards (another replica may be ahead)."""
        async with self._sessions.begin() as s:
            rec = await s.get(LearningSnapshot, (tenant_id, component))
            if rec is None:
                s.add(LearningSnapshot(tenant_id=tenant_id, component=component, seq=seq,
                                       state=state, updated_at=_now()))
            elif seq > rec.seq:
                rec.seq, rec.state, rec.updated_at = seq, state, _now()

    async def delete_snapshot(self, tenant_id: str, component: str) -> None:
        async with self._sessions.begin() as s:
            await s.execute(delete(LearningSnapshot).where(
                LearningSnapshot.tenant_id == tenant_id, LearningSnapshot.component == component))

    # ------------------------------------------------------------------
    # Erasure receipts
    # ------------------------------------------------------------------

    async def put_receipt(self, tenant_id: str, receipt: dict[str, Any]) -> None:
        body = receipt["body"]
        async with self._sessions.begin() as s:
            s.add(ErasureReceiptRecord(
                receipt_id=body["receipt_id"], tenant_id=tenant_id, user_id=body["user_id"],
                body=body, signature=receipt["signature"], alg=receipt["alg"],
            ))

    async def get_receipt(self, tenant_id: str, receipt_id: str) -> dict[str, Any] | None:
        async with self._sessions() as s:
            rec = await s.get(ErasureReceiptRecord, receipt_id)
            if rec is None or rec.tenant_id != tenant_id:
                return None
            return {"body": rec.body, "signature": rec.signature, "alg": rec.alg}

    # ------------------------------------------------------------------
    # Retrieval ledger
    # ------------------------------------------------------------------

    async def put_ledger(
        self, tenant_id: str, retrieval_id: str, user_id: str, signals: dict[str, Any],
    ) -> None:
        async with self._sessions.begin() as s:
            s.add(RetrievalLedgerRecord(retrieval_id=retrieval_id, tenant_id=tenant_id,
                                        user_id=user_id, signals=signals))

    async def get_ledger(self, tenant_id: str, retrieval_id: str) -> dict[str, Any] | None:
        async with self._sessions() as s:
            rec = await s.get(RetrievalLedgerRecord, retrieval_id)
            if rec is None or rec.tenant_id != tenant_id:
                return None
            return {"user_id": rec.user_id, "signals": rec.signals, "consumed": rec.consumed}

    async def consume_ledger(self, tenant_id: str, retrieval_id: str) -> bool:
        """Atomically mark consumed. Returns False if it was already consumed (replay)."""
        async with self._sessions.begin() as s:
            res = await s.execute(
                update(RetrievalLedgerRecord)
                .where(RetrievalLedgerRecord.retrieval_id == retrieval_id,
                       RetrievalLedgerRecord.tenant_id == tenant_id,
                       RetrievalLedgerRecord.consumed.is_(False))
                .values(consumed=True)
            )
            return res.rowcount == 1

    async def prune_ledger(self, older_than: timedelta) -> int:
        async with self._sessions.begin() as s:
            res = await s.execute(delete(RetrievalLedgerRecord)
                                  .where(RetrievalLedgerRecord.created_at < _now() - older_than))
            return res.rowcount or 0

    # ------------------------------------------------------------------
    # API keys
    # ------------------------------------------------------------------

    async def create_api_key(self, record: ApiKeyRecord) -> None:
        async with self._sessions.begin() as s:
            s.add(record)

    async def find_api_key(self, key_hash: str) -> ApiKeyRecord | None:
        async with self._sessions() as s:
            return (await s.execute(
                select(ApiKeyRecord).where(ApiKeyRecord.key_hash == key_hash)
            )).scalar_one_or_none()

    async def touch_api_key(self, key_id: str) -> None:
        async with self._sessions.begin() as s:
            await s.execute(update(ApiKeyRecord).where(ApiKeyRecord.key_id == key_id)
                            .values(last_used_at=_now()))

    async def list_api_keys(self, tenant_id: str) -> list[ApiKeyRecord]:
        async with self._sessions() as s:
            return list((await s.execute(
                select(ApiKeyRecord).where(ApiKeyRecord.tenant_id == tenant_id)
                .order_by(ApiKeyRecord.created_at)
            )).scalars())

    async def revoke_api_key(self, tenant_id: str, key_id: str) -> bool:
        async with self._sessions.begin() as s:
            res = await s.execute(
                update(ApiKeyRecord)
                .where(ApiKeyRecord.key_id == key_id, ApiKeyRecord.tenant_id == tenant_id,
                       ApiKeyRecord.revoked_at.is_(None))
                .values(revoked_at=_now()))
            return res.rowcount == 1

    # ------------------------------------------------------------------
    # Idempotency
    # ------------------------------------------------------------------

    async def claim_idempotency(
        self, tenant_id: str, key: str, route: str, request_hash: str,
    ) -> tuple[str, IdempotencyRecord | None]:
        """Returns ("claimed", None) | ("replay", rec) | ("conflict", rec) | ("in_flight", rec)."""
        try:
            async with self._sessions.begin() as s:
                s.add(IdempotencyRecord(tenant_id=tenant_id, key=key, route=route,
                                        request_hash=request_hash))
            return "claimed", None
        except IntegrityError:
            async with self._sessions() as s:
                rec = await s.get(IdempotencyRecord, (tenant_id, key))
            if rec is None:  # raced with a release; let the caller retry
                return "in_flight", None
            if rec.request_hash != request_hash or rec.route != route:
                return "conflict", rec
            return ("replay", rec) if rec.status_code is not None else ("in_flight", rec)

    async def complete_idempotency(
        self, tenant_id: str, key: str, status_code: int, response: Any,
    ) -> None:
        async with self._sessions.begin() as s:
            rec = await s.get(IdempotencyRecord, (tenant_id, key))
            if rec is not None:
                rec.status_code, rec.response = status_code, response

    async def release_idempotency(self, tenant_id: str, key: str) -> None:
        """Handler failed: free the key so the client can retry."""
        async with self._sessions.begin() as s:
            await s.execute(delete(IdempotencyRecord).where(
                IdempotencyRecord.tenant_id == tenant_id, IdempotencyRecord.key == key,
                IdempotencyRecord.status_code.is_(None)))

    async def prune_idempotency(self, older_than: timedelta) -> int:
        async with self._sessions.begin() as s:
            res = await s.execute(delete(IdempotencyRecord)
                                  .where(IdempotencyRecord.created_at < _now() - older_than))
            return res.rowcount or 0

    # ------------------------------------------------------------------
    # Vector-sync outbox
    # ------------------------------------------------------------------

    async def enqueue_outbox(
        self, tenant_id: str, memory_id: str, op: str, fields: dict[str, Any] | None = None,
    ) -> None:
        async with self._sessions.begin() as s:
            s.add(OutboxRecord(tenant_id=tenant_id, memory_id=memory_id, op=op, fields=fields or {}))

    async def cancel_outbox(self, tenant_id: str, memory_id: str, ops: tuple[str, ...]) -> int:
        async with self._sessions.begin() as s:
            res = await s.execute(
                update(OutboxRecord)
                .where(OutboxRecord.tenant_id == tenant_id, OutboxRecord.memory_id == memory_id,
                       OutboxRecord.state.in_(("pending", "leased")), OutboxRecord.op.in_(ops))
                .values(state="cancelled"))
            return res.rowcount or 0

    async def due_outbox(self, limit: int = 100, lease_seconds: int = 120) -> list[OutboxRecord]:
        """Claim due work exclusively. Postgres: FOR UPDATE SKIP LOCKED, so concurrent workers
        on different replicas get disjoint batches. Claimed rows are leased; a crashed worker's
        lease expires and the rows become due again (``next_attempt_at`` doubles as the lease)."""
        if self._engine.dialect.name != "postgresql":
            async with self._claim_lock:
                return await self._claim(limit, lease_seconds)
        return await self._claim(limit, lease_seconds)

    async def _claim(self, limit: int, lease_seconds: int) -> list[OutboxRecord]:
        now = _now()
        async with self._sessions.begin() as s:
            stmt = (select(OutboxRecord)
                    .where(OutboxRecord.state.in_(("pending", "leased")),
                           OutboxRecord.next_attempt_at <= now)
                    .order_by(OutboxRecord.seq).limit(limit))
            if self._engine.dialect.name == "postgresql":
                stmt = stmt.with_for_update(skip_locked=True)
            rows = list((await s.execute(stmt)).scalars())
            for r in rows:
                r.state = "leased"
                r.next_attempt_at = now + timedelta(seconds=lease_seconds)
            return rows

    async def finish_outbox(self, seq: int) -> None:
        async with self._sessions.begin() as s:
            await s.execute(update(OutboxRecord).where(OutboxRecord.seq == seq).values(state="done"))

    async def retry_outbox(self, seq: int, error: str, max_attempts: int) -> str:
        async with self._sessions.begin() as s:
            rec = await s.get(OutboxRecord, seq)
            if rec is None:
                return "missing"
            rec.attempts += 1
            rec.last_error = error[:2000]
            if rec.attempts >= max_attempts:
                rec.state = "dead"
            else:
                rec.state = "pending"
                rec.next_attempt_at = _now() + timedelta(seconds=min(3600, 2 ** rec.attempts))
            return rec.state

    async def outbox_counts(self) -> dict[str, int]:
        async with self._sessions() as s:
            rows = await s.execute(select(OutboxRecord.state, func.count()).group_by(OutboxRecord.state))
            return {state: int(n) for state, n in rows.all()}

    # ------------------------------------------------------------------
    # Audit trail
    # ------------------------------------------------------------------

    async def record_audit(self, tenant_id: str, key_id: str, principal: str, method: str,
                           route: str, status: int) -> None:
        async with self._sessions.begin() as s:
            s.add(AuditEvent(tenant_id=tenant_id, key_id=key_id, principal=principal,
                             method=method, route=route, status=status))

    async def list_audit(self, tenant_id: str, limit: int = 100) -> list[AuditEvent]:
        async with self._sessions() as s:
            return list((await s.execute(
                select(AuditEvent).where(AuditEvent.tenant_id == tenant_id)
                .order_by(AuditEvent.seq.desc()).limit(limit)
            )).scalars())
