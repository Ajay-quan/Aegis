"""SQLAlchemy ORM models for AegisMem relational store."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    JSON, Boolean, DateTime, Float, Integer, String, Text,
    ForeignKey, Index,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_id() -> str:
    return str(uuid.uuid4())


class Base(DeclarativeBase):
    pass


class MemoryRecord(Base):
    __tablename__ = "memories"
    __table_args__ = (
        Index("ix_memories_tenant_user", "tenant_id", "user_id", "status"),
        Index("ix_memories_user_namespace", "user_id", "namespace"),
        Index("ix_memories_status", "status"),
        Index("ix_memories_type", "memory_type"),
        Index("ix_memories_created", "created_at"),
    )

    memory_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, default="default",
                                           server_default="default")
    namespace: Mapped[str] = mapped_column(String(255), nullable=False)
    user_id: Mapped[str] = mapped_column(String(255), nullable=False)
    agent_id: Mapped[str] = mapped_column(String(255), default="")
    memory_type: Mapped[str] = mapped_column(String(50), nullable=False)
    memory_layer: Mapped[str] = mapped_column(String(20), nullable=False, default="episodic",
                                              server_default="episodic")
    content: Mapped[str] = mapped_column(Text, nullable=False)
    source_type: Mapped[str] = mapped_column(String(50), default="user_message")
    source_ref: Mapped[str] = mapped_column(String(255), default="")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    event_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    importance_score: Mapped[float] = mapped_column(Float, default=0.5)
    recency_score: Mapped[float] = mapped_column(Float, default=1.0)
    confidence_score: Mapped[float] = mapped_column(Float, default=0.8)
    access_count: Mapped[int] = mapped_column(Integer, default=0)
    retrieval_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    successful_retrieval_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0,
                                                            server_default="0")

    version: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(50), default="active")
    contradiction_status: Mapped[str] = mapped_column(String(50), default="none")

    parent_memory_ids: Mapped[list] = mapped_column(JSON, default=list)
    contradicted_by: Mapped[list] = mapped_column(JSON, nullable=True, default=list)
    tags: Mapped[list] = mapped_column(JSON, default=list)
    extra_metadata: Mapped[dict] = mapped_column(JSON, default=dict)


class FactRecord(Base):
    __tablename__ = "facts"
    __table_args__ = (
        Index("ix_facts_user", "user_id"),
        Index("ix_facts_subject", "subject"),
    )

    fact_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(String(255), nullable=False)
    agent_id: Mapped[str] = mapped_column(String(255), default="")
    namespace: Mapped[str] = mapped_column(String(255), nullable=False)
    subject: Mapped[str] = mapped_column(String(500), nullable=False)
    predicate: Mapped[str] = mapped_column(String(255), nullable=False)
    object: Mapped[str] = mapped_column(String(500), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, default=0.9)
    source_memory_ids: Mapped[list] = mapped_column(JSON, default=list)
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    status: Mapped[str] = mapped_column(String(50), default="active")


class ReflectionRecord(Base):
    __tablename__ = "reflections"

    reflection_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(String(255), nullable=False)
    agent_id: Mapped[str] = mapped_column(String(255), default="")
    namespace: Mapped[str] = mapped_column(String(255), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    derivation_ids: Mapped[list] = mapped_column(JSON, default=list)
    confidence: Mapped[float] = mapped_column(Float, default=0.7)
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ContradictionRecord(Base):
    __tablename__ = "contradictions"

    report_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    memory_a_id: Mapped[str] = mapped_column(String(36), nullable=False)
    memory_b_id: Mapped[str] = mapped_column(String(36), nullable=False)
    contradiction_description: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, default=0.8)
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    resolved: Mapped[bool] = mapped_column(Boolean, default=False)
    resolution_note: Mapped[str] = mapped_column(Text, default="")
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class MemoryOperationLog(Base):
    __tablename__ = "memory_operation_logs"
    __table_args__ = (
        Index("ix_logs_memory_id", "memory_id"),
        Index("ix_logs_user_id", "user_id"),
        Index("ix_logs_created_at", "created_at"),
    )

    log_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    memory_id: Mapped[str] = mapped_column(String(36), nullable=False)
    user_id: Mapped[str] = mapped_column(String(255), nullable=False)
    operation: Mapped[str] = mapped_column(String(50), nullable=False)
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class EvaluationResult(Base):
    __tablename__ = "evaluation_results"

    result_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    eval_name: Mapped[str] = mapped_column(String(255), nullable=False)
    run_id: Mapped[str] = mapped_column(String(255), nullable=False)
    metrics: Mapped[dict] = mapped_column(JSON, default=dict)
    config: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
