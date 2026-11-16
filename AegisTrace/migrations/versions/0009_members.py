# SPDX-License-Identifier: FSL-1.1-ALv2
# Copyright 2026 AegisTrace contributors
"""Organization members and roles (Owner, Admin, Developer, Viewer).

A signed-in person acts in an organization only as a member. Their effective
permissions are the intersection of what the identity provider's token allows
and what their role allows. The first person to sign in to an organization with
no members becomes its owner (bootstrap).

Revision ID: 0009
Revises: 0008
"""

from alembic import op

revision = "0009"
down_revision = "0008"


def upgrade() -> None:
    op.execute("""
CREATE TABLE members (
    tenant_id text NOT NULL REFERENCES tenants(id),
    subject text NOT NULL,                          -- the identity provider's user id (token `sub`)
    role text NOT NULL CHECK (role IN ('owner', 'admin', 'developer', 'viewer')),
    added_by text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, subject)
);
GRANT SELECT, INSERT, UPDATE, DELETE ON members TO aegis_app;
ALTER TABLE members ENABLE ROW LEVEL SECURITY; ALTER TABLE members FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON members TO aegis_app
    USING (tenant_id = current_setting('app.tenant_id', true))
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true));

-- Never leave an organization without an owner, whatever path the change takes.
CREATE FUNCTION members_keep_an_owner() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF (TG_OP = 'DELETE' OR NEW.role <> 'owner') AND OLD.role = 'owner'
     AND NOT EXISTS (SELECT 1 FROM members m WHERE m.tenant_id = OLD.tenant_id AND m.role = 'owner'
                     AND m.subject <> OLD.subject) THEN
    RAISE EXCEPTION 'an organization must keep at least one owner';
  END IF;
  RETURN COALESCE(NEW, OLD);
END $$;
CREATE TRIGGER members_keep_an_owner BEFORE UPDATE OR DELETE ON members
    FOR EACH ROW EXECUTE FUNCTION members_keep_an_owner();
""")


def downgrade() -> None:
    op.execute("DROP TABLE members; DROP FUNCTION members_keep_an_owner();")
