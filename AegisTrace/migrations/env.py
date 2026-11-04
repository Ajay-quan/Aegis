# SPDX-License-Identifier: FSL-1.1-ALv2
# Copyright 2026 AegisTrace contributors
"""Migrations run as the schema owner (AEGIS_OWNER_DATABASE_URL), never as the app role."""

import os

from alembic import context
from sqlalchemy import create_engine

url = os.environ["AEGIS_OWNER_DATABASE_URL"]
engine = create_engine(url)
with engine.begin() as conn:
    context.configure(connection=conn, target_metadata=None, transaction_per_migration=True)
    with context.begin_transaction():
        context.run_migrations()
