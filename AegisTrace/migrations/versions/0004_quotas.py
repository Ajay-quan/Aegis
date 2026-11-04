# SPDX-License-Identifier: FSL-1.1-ALv2
# Copyright 2026 AegisTrace contributors
"""Per-tenant concurrent-run quota.

Revision ID: 0004
Revises: 0003
"""

from alembic import op

revision = "0004"
down_revision = "0003"


def upgrade() -> None:
    op.execute(
        "ALTER TABLE tenants ADD COLUMN max_active_runs integer NOT NULL DEFAULT 100 CHECK (max_active_runs > 0)"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE tenants DROP COLUMN max_active_runs")
