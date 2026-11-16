# SPDX-License-Identifier: FSL-1.1-ALv2
# Copyright 2026 AegisTrace contributors
"""Token usage per model call, and each organization's model price list.

Cost is computed from the organization's own prices (Aegis ships none: provider
prices change). It is an estimate from those prices, never provider billing.
Amounts are integer micro-dollars so sums are exact.

Revision ID: 0008
Revises: 0007
"""

from alembic import op

revision = "0008"
down_revision = "0007"


def upgrade() -> None:
    op.execute("""
CREATE TABLE model_usage (
    id bigserial PRIMARY KEY,
    tenant_id text NOT NULL REFERENCES tenants(id),
    run_id text NOT NULL,
    agent_id text NOT NULL,
    step integer NOT NULL,
    provider text NOT NULL,
    model_id text NOT NULL,
    input_tokens integer NOT NULL CHECK (input_tokens >= 0),
    output_tokens integer NOT NULL CHECK (output_tokens >= 0),
    source text NOT NULL CHECK (source IN ('provider', 'estimate')),
    cost_micro_usd bigint,                  -- NULL: no price set for this model
    latency_ms integer,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (run_id, step)                   -- one row per model call, even if a step is retried
);
CREATE INDEX model_usage_tenant_time ON model_usage (tenant_id, created_at DESC);
CREATE INDEX model_usage_run ON model_usage (run_id);

CREATE TABLE model_prices (
    tenant_id text NOT NULL REFERENCES tenants(id),
    provider text NOT NULL,
    model_id text NOT NULL,
    input_micro_usd_per_mtok bigint NOT NULL CHECK (input_micro_usd_per_mtok >= 0),
    output_micro_usd_per_mtok bigint NOT NULL CHECK (output_micro_usd_per_mtok >= 0),
    updated_by text NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, provider, model_id)
);

GRANT SELECT, INSERT, UPDATE ON model_usage TO aegis_app;
GRANT USAGE ON SEQUENCE model_usage_id_seq TO aegis_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON model_prices TO aegis_app;
""")
    for t in ("model_usage", "model_prices"):
        op.execute(f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY; ALTER TABLE {t} FORCE ROW LEVEL SECURITY;")
        op.execute(
            f"CREATE POLICY tenant_isolation ON {t} TO aegis_app "
            "USING (tenant_id = current_setting('app.tenant_id', true)) "
            "WITH CHECK (tenant_id = current_setting('app.tenant_id', true))"
        )


def downgrade() -> None:
    op.execute("DROP TABLE model_prices, model_usage;")
