# SPDX-License-Identifier: FSL-1.1-ALv2
# Copyright 2026 AegisTrace contributors
"""Per-organization rule settings with an append-only change history.

Revision ID: 0005
Revises: 0004
"""

from alembic import op

revision = "0005"
down_revision = "0004"


def upgrade() -> None:
    op.execute("""
CREATE TABLE tenant_rules (
    tenant_id text PRIMARY KEY REFERENCES tenants(id),
    settings jsonb NOT NULL,
    version integer NOT NULL DEFAULT 1,
    updated_by text NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE tenant_rules_history (
    id bigserial PRIMARY KEY,
    tenant_id text NOT NULL REFERENCES tenants(id),
    version integer NOT NULL,
    settings jsonb NOT NULL,
    changed_by text NOT NULL,
    source text NOT NULL CHECK (source IN ('dashboard', 'api', 'file')),
    note text,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, version)
);
CREATE TRIGGER tenant_rules_history_append_only BEFORE UPDATE OR DELETE ON tenant_rules_history
    FOR EACH ROW EXECUTE FUNCTION forbid_mutation();
GRANT SELECT, INSERT, UPDATE ON tenant_rules TO aegis_app;
GRANT SELECT, INSERT ON tenant_rules_history TO aegis_app;
GRANT USAGE ON SEQUENCE tenant_rules_history_id_seq TO aegis_app;
""")
    for t in ("tenant_rules", "tenant_rules_history"):
        op.execute(f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY; ALTER TABLE {t} FORCE ROW LEVEL SECURITY;")
        op.execute(
            f"CREATE POLICY tenant_isolation ON {t} TO aegis_app "
            "USING (tenant_id = current_setting('app.tenant_id', true)) "
            "WITH CHECK (tenant_id = current_setting('app.tenant_id', true))"
        )


def downgrade() -> None:
    op.execute("DROP TABLE tenant_rules_history, tenant_rules;")
