# SPDX-License-Identifier: FSL-1.1-ALv2
# Copyright 2026 AegisTrace contributors
"""Envelope encryption of payload content, crypto-shredding, legal hold, retention.

Each run gets its own data key, stored only wrapped by the platform key
(KMS in production). Erasing a run destroys its wrapped key: the content
becomes unrecoverable while every digest, hash and signature stays intact, so
the evidence chain still verifies (payloads are then "withheld").

Revision ID: 0006
Revises: 0005
"""

from alembic import op
from sqlalchemy import text

revision = "0006"
down_revision = "0005"


def upgrade() -> None:
    op.execute("""
CREATE TABLE payload_keys (
    run_id text PRIMARY KEY,             -- no FK: the key is created just before the run row (its input is sealed)
    tenant_id text NOT NULL REFERENCES tenants(id),
    kek_id text NOT NULL,
    wrapped bytea,                       -- NULL once shredded
    created_at timestamptz NOT NULL DEFAULT now(),
    shredded_at timestamptz,
    legal_hold boolean NOT NULL DEFAULT false,
    CHECK ((wrapped IS NULL) = (shredded_at IS NOT NULL))
);
CREATE INDEX payload_keys_tenant ON payload_keys (tenant_id, created_at);

-- A shredded key can never come back, and a held key cannot be shredded.
CREATE FUNCTION payload_keys_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN RAISE EXCEPTION 'payload_keys rows are never deleted; shred instead'; END IF;
  IF OLD.shredded_at IS NOT NULL AND (NEW.wrapped IS NOT NULL OR NEW.shredded_at IS DISTINCT FROM OLD.shredded_at) THEN
    RAISE EXCEPTION 'a shredded payload key cannot be restored';
  END IF;
  IF NEW.wrapped IS NULL AND OLD.wrapped IS NOT NULL AND OLD.legal_hold THEN
    RAISE EXCEPTION 'run % is under legal hold', OLD.run_id;
  END IF;
  IF NEW.wrapped IS DISTINCT FROM OLD.wrapped AND NEW.wrapped IS NOT NULL THEN
    RAISE EXCEPTION 'payload keys cannot be replaced';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER payload_keys_guard BEFORE UPDATE OR DELETE ON payload_keys
    FOR EACH ROW EXECUTE FUNCTION payload_keys_guard();

-- Who erased what, when and why (content-free, append-only).
CREATE TABLE erasures (
    id text PRIMARY KEY,
    tenant_id text NOT NULL REFERENCES tenants(id),
    scope text NOT NULL CHECK (scope IN ('run', 'tenant', 'retention')),
    run_ids text[] NOT NULL,
    actor_id text NOT NULL,
    reason text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TRIGGER erasures_append_only BEFORE UPDATE OR DELETE ON erasures
    FOR EACH ROW EXECUTE FUNCTION forbid_mutation();

GRANT SELECT, INSERT, UPDATE ON payload_keys TO aegis_app;
GRANT SELECT, INSERT ON erasures TO aegis_app;
""")
    for t in ("payload_keys", "erasures"):
        op.execute(f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY; ALTER TABLE {t} FORCE ROW LEVEL SECURITY;")
        op.execute(
            f"CREATE POLICY tenant_isolation ON {t} TO aegis_app "
            "USING (tenant_id = current_setting('app.tenant_id', true)) "
            "WITH CHECK (tenant_id = current_setting('app.tenant_id', true))"
        )
    # Retention runs across tenants from the worker's maintenance loop through one
    # SECURITY DEFINER function. It is the only cross-tenant path: it can only
    # shred (never read content), honours legal hold and each tenant's own
    # setting, and records every erasure. The function runs as the schema owner,
    # so the owner (who could disable RLS on its own tables anyway) gets explicit
    # policies for exactly what the function touches; aegis_app stays tenant-scoped.
    owner = op.get_bind().execute(text("SELECT quote_ident(current_user)")).scalar_one()
    for table, cmd in (("payload_keys", "ALL"), ("erasures", "INSERT"), ("tenant_rules", "SELECT"), ("runs", "SELECT")):
        using = "" if cmd == "INSERT" else " USING (true)"
        check = " WITH CHECK (true)" if cmd in ("ALL", "INSERT") else ""
        op.execute(f"CREATE POLICY retention_owner ON {table} FOR {cmd} TO {owner}{using}{check}")
    op.execute("""
CREATE FUNCTION apply_payload_retention() RETURNS integer
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE t record; ids text[]; n integer := 0;
BEGIN
  FOR t IN SELECT tenant_id, (settings->>'payload_retention_days')::int AS days FROM tenant_rules
           WHERE (settings->>'payload_retention_days') ~ '^[0-9]+$' AND (settings->>'payload_retention_days')::int > 0
  LOOP
    WITH s AS (
      UPDATE payload_keys k SET wrapped = NULL, shredded_at = now()
      FROM runs r
      WHERE k.run_id = r.id AND k.tenant_id = t.tenant_id AND k.wrapped IS NOT NULL AND NOT k.legal_hold
        AND r.state IN ('SUCCEEDED', 'FAILED', 'CANCELLED', 'TIMED_OUT')
        AND r.updated_at < now() - make_interval(days => t.days)
      RETURNING k.run_id)
    SELECT array_agg(run_id) INTO ids FROM s;
    IF ids IS NOT NULL THEN
      INSERT INTO erasures (id, tenant_id, scope, run_ids, actor_id, reason)
      VALUES ('era_' || substr(replace(gen_random_uuid()::text, '-', ''), 1, 24), t.tenant_id, 'retention', ids,
              'system', 'retention: ' || t.days || ' days');
      n := n + cardinality(ids);
    END IF;
  END LOOP;
  RETURN n;
END $$;
REVOKE ALL ON FUNCTION apply_payload_retention() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION apply_payload_retention() TO aegis_app;
""")


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS retention_owner ON tenant_rules; DROP POLICY IF EXISTS retention_owner ON runs;")
    op.execute("DROP FUNCTION apply_payload_retention(); DROP TABLE erasures, payload_keys;")
    op.execute("DROP FUNCTION payload_keys_guard();")
