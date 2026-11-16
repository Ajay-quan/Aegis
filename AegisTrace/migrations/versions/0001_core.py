# SPDX-License-Identifier: FSL-1.1-ALv2
# Copyright 2026 AegisTrace contributors
"""Core schema: tenants, projects, agents, runs, events, outbox, checkpoints.

Revision ID: 0001
Revises:
"""

from alembic import op

revision = "0001"
down_revision = None

TENANT_TABLES = ["projects", "agents", "runs", "events", "outbox", "checkpoints", "idempotency_keys"]

UPGRADE = """
CREATE TABLE tenants (
    id text PRIMARY KEY CHECK (id ~ '^tnt_[a-z0-9_]{1,60}$'),
    name text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE projects (
    id text PRIMARY KEY,
    tenant_id text NOT NULL REFERENCES tenants(id),
    name text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, id),
    UNIQUE (tenant_id, name)
);

CREATE TABLE agents (
    id text PRIMARY KEY,
    tenant_id text NOT NULL,
    project_id text NOT NULL,
    name text NOT NULL,
    model_provider text NOT NULL,
    model_id text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    -- Composite FK: an agent cannot point at another tenant's project.
    FOREIGN KEY (tenant_id, project_id) REFERENCES projects(tenant_id, id),
    UNIQUE (tenant_id, id),
    UNIQUE (tenant_id, project_id, name)
);

CREATE TABLE runs (
    id text PRIMARY KEY,
    tenant_id text NOT NULL,
    project_id text NOT NULL,
    agent_id text NOT NULL,
    state text NOT NULL,
    input jsonb NOT NULL,
    head_hash text NOT NULL,
    last_sequence integer NOT NULL CHECK (last_sequence >= 0),
    attempt integer NOT NULL DEFAULT 0,
    max_attempts integer NOT NULL DEFAULT 3,
    lease_owner text,
    lease_expires_at timestamptz,
    fencing_token bigint NOT NULL DEFAULT 0,
    next_attempt_at timestamptz,
    deadline_at timestamptz,
    result jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY (tenant_id, agent_id) REFERENCES agents(tenant_id, id),
    FOREIGN KEY (tenant_id, project_id) REFERENCES projects(tenant_id, id),
    UNIQUE (tenant_id, id)
);
CREATE INDEX runs_tenant_state ON runs (tenant_id, state, created_at DESC);
CREATE INDEX runs_lease ON runs (state, lease_expires_at) WHERE lease_owner IS NOT NULL;

CREATE TABLE events (
    event_id text PRIMARY KEY,
    tenant_id text NOT NULL,
    run_id text NOT NULL,
    sequence_number integer NOT NULL CHECK (sequence_number >= 1),
    event_type text NOT NULL,
    current_event_hash text NOT NULL,
    record jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY (tenant_id, run_id) REFERENCES runs(tenant_id, id),
    UNIQUE (run_id, sequence_number)
);

CREATE TABLE checkpoints (
    id bigserial PRIMARY KEY,
    tenant_id text NOT NULL,
    run_id text NOT NULL,
    last_sequence integer NOT NULL,
    key_id text NOT NULL,
    record jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY (tenant_id, run_id) REFERENCES runs(tenant_id, id),
    UNIQUE (run_id, last_sequence)
);

CREATE TABLE outbox (
    id bigserial PRIMARY KEY,
    tenant_id text NOT NULL REFERENCES tenants(id),
    run_id text,
    topic text NOT NULL,
    payload jsonb NOT NULL,
    status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'dispatched', 'dead')),
    attempts integer NOT NULL DEFAULT 0,
    last_error text,
    available_at timestamptz NOT NULL DEFAULT now(),
    created_at timestamptz NOT NULL DEFAULT now(),
    dispatched_at timestamptz
);
CREATE INDEX outbox_pending ON outbox (available_at) WHERE status = 'pending';

CREATE TABLE idempotency_keys (
    tenant_id text NOT NULL REFERENCES tenants(id),
    key text NOT NULL,
    request_digest text NOT NULL,
    resource_id text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, key)
);

-- Evidence is append-only, even for the owner role.
CREATE FUNCTION forbid_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'append-only table: % on % rejected', TG_OP, TG_TABLE_NAME;
END $$;
CREATE TRIGGER events_append_only BEFORE UPDATE OR DELETE ON events
    FOR EACH ROW EXECUTE FUNCTION forbid_mutation();
CREATE TRIGGER checkpoints_append_only BEFORE UPDATE OR DELETE ON checkpoints
    FOR EACH ROW EXECUTE FUNCTION forbid_mutation();

GRANT USAGE ON SCHEMA public TO aegis_app, aegis_dispatcher;
GRANT SELECT ON tenants TO aegis_app;
GRANT SELECT, INSERT ON projects, agents, idempotency_keys TO aegis_app;
GRANT SELECT, INSERT, UPDATE ON runs TO aegis_app;
GRANT SELECT, INSERT ON events, checkpoints, outbox TO aegis_app;
GRANT USAGE ON SEQUENCE checkpoints_id_seq, outbox_id_seq TO aegis_app;
GRANT SELECT, UPDATE ON outbox TO aegis_dispatcher;
"""


def upgrade() -> None:
    op.execute(UPGRADE)
    # Tenant isolation: the app role sees only rows of the tenant bound to the
    # current transaction (SET LOCAL app.tenant_id). Unset => no rows.
    op.execute("ALTER TABLE tenants ENABLE ROW LEVEL SECURITY; ALTER TABLE tenants FORCE ROW LEVEL SECURITY;")
    op.execute(
        "CREATE POLICY tenant_isolation ON tenants TO aegis_app USING (id = current_setting('app.tenant_id', true))"
    )
    for t in TENANT_TABLES:
        op.execute(f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY; ALTER TABLE {t} FORCE ROW LEVEL SECURITY;")
        op.execute(
            f"CREATE POLICY tenant_isolation ON {t} TO aegis_app "
            "USING (tenant_id = current_setting('app.tenant_id', true)) "
            "WITH CHECK (tenant_id = current_setting('app.tenant_id', true))"
        )
    op.execute("CREATE POLICY dispatcher_all ON outbox TO aegis_dispatcher USING (true) WITH CHECK (true)")


def downgrade() -> None:
    op.execute(
        "DROP TABLE idempotency_keys, outbox, checkpoints, events, runs, agents, projects, tenants CASCADE;"
        "DROP FUNCTION forbid_mutation();"
    )
