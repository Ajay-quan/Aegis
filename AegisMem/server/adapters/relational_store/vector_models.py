"""Vector table for single-store (pgvector) deployments."""
from __future__ import annotations

import os

from pgvector.sqlalchemy import Vector
from sqlalchemy import JSON, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from .models import Base

# Fixed at migration time; must match the embedding model (see migration 0003).
VECTOR_DIM = int(os.environ.get("AEGIS_VECTOR_DIM", "384"))


class MemoryVector(Base):
    __tablename__ = "memory_vectors"
    __table_args__ = (
        Index("ix_memory_vectors_scope", "tenant_id", "user_id", "status"),
        # Postgres only (ignored by other dialects): approximate-NN index for cosine search.
        Index("ix_memory_vectors_hnsw", "embedding", postgresql_using="hnsw",
              postgresql_ops={"embedding": "vector_cosine_ops"}),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    user_id: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="active")
    embedding: Mapped[list] = mapped_column(Vector(VECTOR_DIM).with_variant(JSON(), "sqlite"))
    payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
