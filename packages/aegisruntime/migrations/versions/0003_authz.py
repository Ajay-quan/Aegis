# SPDX-License-Identifier: FSL-1.1-ALv2
# Copyright 2026 AegisTrace contributors
"""Tool grants, policy decisions, approvals.

Revision ID: 0003
Revises: 0002
"""

from alembic import op

revision = "0003"
down_revision = "0002"

TABLES = ["tool_grants", "policy_decisions", "approvals"]


def upgrade() -> None:
    op.execute("""
CREATE TABLE tool_grants (
    tenant_id text NOT NULL,
    agent_id text NOT NULL,
    tool text NOT NULL,
    max_risk_class integer NOT NULL CHECK (max_risk_class BETWEEN 0 AND 4),
    allowed_hosts text[] NOT NULL DEFAULT '{}',
    granted_by text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, agent_id, tool),
    FOREIGN KEY (tenant_id, agent_id) REFERENCES agents(tenant_id, id)
);

CREATE TABLE policy_decisions (
    decision_id text PRIMARY KEY,
    tenant_id text NOT NULL,
    run_id text NOT NULL,
    principal text NOT NULL,
    tool text NOT NULL,
    action_digest text NOT NULL,
    resource text,
    policy_revision text NOT NULL,
    decision text NOT NULL CHECK (decision IN ('allow', 'deny', 'require_approval')),
    reason text NOT NULL,
    input_digest text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY (tenant_id, run_id) REFERENCES runs(tenant_id, id)
);

CREATE TABLE approvals (
    id text PRIMARY KEY,
    tenant_id text NOT NULL,
    run_id text NOT NULL,
    agent_id text NOT NULL,
    tool text NOT NULL,
    action_digest text NOT NULL,
    arguments_digest text NOT NULL,
    resource text,
    risk_class integer NOT NULL,
    policy_revision text NOT NULL,
    summary jsonb NOT NULL,
    status text NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'approved', 'rejected', 'consumed', 'expired')),
    requested_at timestamptz NOT NULL DEFAULT now(),
    expires_at timestamptz NOT NULL,
    decided_by text,
    decided_at timestamptz,
    consumed_at timestamptz,
    FOREIGN KEY (tenant_id, run_id) REFERENCES runs(tenant_id, id)
);
-- At most one live approval per exact action in a run.
CREATE UNIQUE INDEX approvals_one_live ON approvals (run_id, action_digest)
    WHERE status IN ('pending', 'approved');

GRANT SELECT, INSERT, DELETE ON tool_grants TO aegis_app;
GRANT SELECT, INSERT ON policy_decisions TO aegis_app;
GRANT SELECT, INSERT, UPDATE ON approvals TO aegis_app;
""")
    for t in TABLES:
        op.execute(f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY; ALTER TABLE {t} FORCE ROW LEVEL SECURITY;")
        op.execute(
            f"CREATE POLICY tenant_isolation ON {t} TO aegis_app "
            "USING (tenant_id = current_setting('app.tenant_id', true)) "
            "WITH CHECK (tenant_id = current_setting('app.tenant_id', true))"
        )


def downgrade() -> None:
    op.execute("DROP TABLE approvals, policy_decisions, tool_grants;")
