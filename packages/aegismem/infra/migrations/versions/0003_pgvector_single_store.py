"""pgvector single-store: memory_vectors table (HNSW cosine index on Postgres)

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-10
"""
import os
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

DIM = int(os.environ.get("AEGIS_VECTOR_DIM", "384"))


def upgrade() -> None:
    is_pg = op.get_bind().dialect.name == "postgresql"
    if is_pg:
        from pgvector.sqlalchemy import Vector
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")
        emb_type = Vector(DIM)
    else:
        emb_type = sa.JSON()
    op.create_table(
        "memory_vectors",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("user_id", sa.String(255), nullable=False),
        sa.Column("status", sa.String(50), nullable=False),
        sa.Column("embedding", emb_type, nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
    )
    op.create_index("ix_memory_vectors_scope", "memory_vectors", ["tenant_id", "user_id", "status"])
    # HNSW on Postgres; other dialects get a plain index (keeps model and schema identical).
    op.create_index("ix_memory_vectors_hnsw", "memory_vectors", ["embedding"],
                    postgresql_using="hnsw", postgresql_ops={"embedding": "vector_cosine_ops"})


def downgrade() -> None:
    op.drop_table("memory_vectors")
