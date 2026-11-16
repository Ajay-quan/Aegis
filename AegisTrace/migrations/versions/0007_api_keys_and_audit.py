# SPDX-License-Identifier: FSL-1.1-ALv2
# Copyright 2026 AegisTrace contributors
"""API keys for the AegisTrace API, and an audit log of administrative actions.

Keys are `aet_<id>_<secret>`; only a peppered HMAC-SHA256 of the whole key is
stored. A request carries only the key, so the tenant is unknown until the key
is found: `api_key_lookup` is the one cross-tenant read, it takes the hash
(i.e. requires possession of the key) and returns only that key's metadata.

Revision ID: 0007
Revises: 0006
"""

from alembic import op
from sqlalchemy import text

revision = "0007"
down_revision = "0006"


def upgrade() -> None:
    op.execute("""
CREATE TABLE api_keys (
    id text PRIMARY KEY,
    tenant_id text NOT NULL REFERENCES tenants(id),
    name text NOT NULL CHECK (length(name) BETWEEN 1 AND 100),
    prefix text NOT NULL,                     -- shown in lists to recognise a key; not secret
    key_hash text NOT NULL UNIQUE,            -- HMAC-SHA256(pepper, full key), hex
    scopes text[] NOT NULL,
    created_by text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    expires_at timestamptz,
    last_used_at timestamptz,
    revoked_at timestamptz,
    revoked_by text
);
CREATE INDEX api_keys_tenant ON api_keys (tenant_id, created_at DESC);

-- A revoked key stays revoked; hashes and scopes never change after creation.
CREATE FUNCTION api_keys_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN RAISE EXCEPTION 'api keys are revoked, never deleted'; END IF;
  IF OLD.revoked_at IS NOT NULL AND NEW.revoked_at IS DISTINCT FROM OLD.revoked_at THEN
    RAISE EXCEPTION 'a revoked key cannot be restored';
  END IF;
  IF NEW.key_hash <> OLD.key_hash OR NEW.scopes <> OLD.scopes OR NEW.tenant_id <> OLD.tenant_id THEN
    RAISE EXCEPTION 'key hash, scopes and tenant are immutable';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER api_keys_guard BEFORE UPDATE OR DELETE ON api_keys FOR EACH ROW EXECUTE FUNCTION api_keys_guard();

CREATE TABLE audit_events (
    id bigserial PRIMARY KEY,
    tenant_id text NOT NULL REFERENCES tenants(id),
    actor_id text NOT NULL,
    action text NOT NULL,                     -- e.g. api_key.created, api_key.revoked
    target text NOT NULL,
    detail jsonb NOT NULL DEFAULT '{}',       -- never secrets or content
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX audit_events_tenant ON audit_events (tenant_id, created_at DESC);
CREATE TRIGGER audit_events_append_only BEFORE UPDATE OR DELETE ON audit_events
    FOR EACH ROW EXECUTE FUNCTION forbid_mutation();

GRANT SELECT, INSERT, UPDATE ON api_keys TO aegis_app;
GRANT SELECT, INSERT ON audit_events TO aegis_app;
GRANT USAGE ON SEQUENCE audit_events_id_seq TO aegis_app;
""")
    for t in ("api_keys", "audit_events"):
        op.execute(f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY; ALTER TABLE {t} FORCE ROW LEVEL SECURITY;")
        op.execute(
            f"CREATE POLICY tenant_isolation ON {t} TO aegis_app "
            "USING (tenant_id = current_setting('app.tenant_id', true)) "
            "WITH CHECK (tenant_id = current_setting('app.tenant_id', true))"
        )
    owner = op.get_bind().execute(text("SELECT quote_ident(current_user)")).scalar_one()
    op.execute(f"CREATE POLICY key_lookup_owner ON api_keys FOR ALL TO {owner} USING (true) WITH CHECK (true)")
    op.execute("""
CREATE FUNCTION api_key_lookup(p_hash text)
RETURNS TABLE (id text, tenant_id text, scopes text[], usable boolean)
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
BEGIN
  -- Record use at most once a minute per key (bounded write amplification).
  UPDATE api_keys k SET last_used_at = now()
   WHERE k.key_hash = p_hash AND k.revoked_at IS NULL
     AND (k.last_used_at IS NULL OR k.last_used_at < now() - interval '1 minute');
  RETURN QUERY
    SELECT k.id, k.tenant_id, k.scopes,
           (k.revoked_at IS NULL AND (k.expires_at IS NULL OR k.expires_at > now()))
      FROM api_keys k WHERE k.key_hash = p_hash;
END $$;
REVOKE ALL ON FUNCTION api_key_lookup(text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION api_key_lookup(text) TO aegis_app;
""")


def downgrade() -> None:
    op.execute("DROP FUNCTION api_key_lookup(text);")
    op.execute("DROP TABLE audit_events, api_keys;")
    op.execute("DROP FUNCTION api_keys_guard();")
