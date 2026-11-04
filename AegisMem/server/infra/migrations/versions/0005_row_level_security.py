"""Postgres row-level security on tenant data (defence in depth)

The application binds ``app.tenant_id`` per transaction (core/tenancy_context.py). These policies
make the database itself refuse rows of other tenants, even if application code has a bug.
FORCE applies the policy to the table owner too. ``app.rls_bypass = 'on'`` is set only by explicit
system jobs (outbox worker, operator CLI). No context at all means no rows: fail closed.

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-10
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLES = ("memories", "memory_vectors")
PREDICATE = ("tenant_id = current_setting('app.tenant_id', true) "
             "OR current_setting('app.rls_bypass', true) = 'on'")


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    for t in TABLES:
        op.execute(f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {t} FORCE ROW LEVEL SECURITY")
        op.execute(f"CREATE POLICY tenant_isolation ON {t} USING ({PREDICATE}) WITH CHECK ({PREDICATE})")


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    for t in TABLES:
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {t}")
        op.execute(f"ALTER TABLE {t} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {t} DISABLE ROW LEVEL SECURITY")
