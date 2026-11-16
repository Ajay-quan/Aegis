# SPDX-License-Identifier: FSL-1.1-ALv2
# Copyright 2026 AegisTrace contributors
"""Cross-tenant scheduling scans that reveal only identifiers.

The app role cannot read other tenants' rows. These SECURITY DEFINER functions
return (tenant_id, run_id) pairs only; all processing then happens inside a
tenant-bound transaction subject to RLS.

Revision ID: 0002
Revises: 0001
"""

from alembic import op

revision = "0002"
down_revision = "0001"


def upgrade() -> None:
    op.execute("""
CREATE FUNCTION scheduler_expired_leases(lim integer)
RETURNS TABLE (tenant_id text, run_id text)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
    SELECT tenant_id, id FROM runs
    WHERE state = 'RUNNING' AND lease_expires_at < now()
    ORDER BY lease_expires_at LIMIT lim
$$;

CREATE FUNCTION scheduler_due_retries(lim integer)
RETURNS TABLE (tenant_id text, run_id text)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
    SELECT tenant_id, id FROM runs
    WHERE state = 'RETRY_SCHEDULED' AND next_attempt_at <= now()
    ORDER BY next_attempt_at LIMIT lim
$$;

CREATE FUNCTION scheduler_overdue_runs(lim integer)
RETURNS TABLE (tenant_id text, run_id text)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
    SELECT tenant_id, id FROM runs
    WHERE deadline_at < now() AND state IN ('QUEUED', 'RUNNING', 'WAITING_FOR_APPROVAL')
    ORDER BY deadline_at LIMIT lim
$$;

REVOKE ALL ON FUNCTION scheduler_expired_leases(integer), scheduler_due_retries(integer),
    scheduler_overdue_runs(integer) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION scheduler_expired_leases(integer), scheduler_due_retries(integer),
    scheduler_overdue_runs(integer) TO aegis_app;
""")


def downgrade() -> None:
    op.execute(
        "DROP FUNCTION scheduler_expired_leases(integer), scheduler_due_retries(integer), "
        "scheduler_overdue_runs(integer);"
    )
