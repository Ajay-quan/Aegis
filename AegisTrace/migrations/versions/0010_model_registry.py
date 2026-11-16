# SPDX-License-Identifier: FSL-1.1-ALv2
# Copyright 2026 AegisTrace contributors
"""Model Hub: each organization's registered model endpoints.

Provider API keys are stored only encrypted (wrapped by the platform key-encryption
key, bound to the organization and registration id) and are never returned.

Revision ID: 0010
Revises: 0009
"""

from alembic import op

revision = "0010"
down_revision = "0009"


def upgrade() -> None:
    op.execute("""
CREATE TABLE model_registrations (
    id text PRIMARY KEY,
    tenant_id text NOT NULL REFERENCES tenants(id),
    name text NOT NULL CHECK (length(name) BETWEEN 1 AND 80),
    provider text NOT NULL CHECK (provider IN ('openai-compatible', 'ollama', 'anthropic', 'mock')),
    base_url text,
    model_id text NOT NULL,
    secret bytea,                              -- provider API key, encrypted; NULL when none
    allow_private_network boolean NOT NULL DEFAULT false,
    status text NOT NULL DEFAULT 'unverified' CHECK (status IN ('unverified', 'connected', 'failed')),
    last_check_at timestamptz,
    last_check_detail text,
    created_by text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, name)
);
GRANT SELECT, INSERT, UPDATE, DELETE ON model_registrations TO aegis_app;
ALTER TABLE model_registrations ENABLE ROW LEVEL SECURITY; ALTER TABLE model_registrations FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON model_registrations TO aegis_app
    USING (tenant_id = current_setting('app.tenant_id', true))
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
""")


def downgrade() -> None:
    op.execute("DROP TABLE model_registrations;")
