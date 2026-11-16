# SPDX-License-Identifier: FSL-1.1-ALv2
# Copyright 2026 AegisTrace contributors
"""Agent Builder: instructions, limits and memory switch per agent, with an append-only version history.

Revision ID: 0011
Revises: 0010
"""

from alembic import op

revision = "0011"
down_revision = "0010"


def upgrade() -> None:
    op.execute("""
ALTER TABLE agents
    ADD COLUMN instructions text NOT NULL DEFAULT '' CHECK (length(instructions) <= 8000),
    ADD COLUMN max_steps integer NOT NULL DEFAULT 20 CHECK (max_steps BETWEEN 1 AND 50),
    ADD COLUMN memory_enabled boolean NOT NULL DEFAULT false,
    ADD COLUMN version integer NOT NULL DEFAULT 1,
    ADD COLUMN updated_at timestamptz NOT NULL DEFAULT now();
GRANT UPDATE ON agents TO aegis_app;

CREATE TABLE agent_versions (
    tenant_id text NOT NULL REFERENCES tenants(id),
    agent_id text NOT NULL,
    version integer NOT NULL,
    config jsonb NOT NULL,           -- name, model, instructions, limits, memory switch (never secrets)
    changed_by text NOT NULL,
    note text,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (agent_id, version)
);
CREATE TRIGGER agent_versions_append_only BEFORE UPDATE OR DELETE ON agent_versions
    FOR EACH ROW EXECUTE FUNCTION forbid_mutation();
GRANT SELECT, INSERT ON agent_versions TO aegis_app;
ALTER TABLE agent_versions ENABLE ROW LEVEL SECURITY; ALTER TABLE agent_versions FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON agent_versions TO aegis_app
    USING (tenant_id = current_setting('app.tenant_id', true))
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
""")


def downgrade() -> None:
    op.execute("DROP TABLE agent_versions;")
    op.execute(
        "ALTER TABLE agents DROP COLUMN instructions, DROP COLUMN max_steps, DROP COLUMN memory_enabled, "
        "DROP COLUMN version, DROP COLUMN updated_at;"
    )
