"""Alembic environment for AegisMem.

URL precedence: ``-x url=...`` > ``AEGIS_MIGRATION_URL`` > settings (sync Postgres URL).
Run: ``alembic upgrade head`` (CI runs upgrade -> downgrade base -> upgrade on every PR).
"""
from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from adapters.relational_store import control_models, vector_models  # noqa: F401  (register tables)
from adapters.relational_store.models import Base
from core.config.settings import settings

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

url = (
    context.get_x_argument(as_dictionary=True).get("url")
    or os.environ.get("AEGIS_MIGRATION_URL")
    or settings.postgres_url_sync
)
# Pin the sync driver: SQLAlchemy's default for bare "postgresql://" differs across versions
# (psycopg2 vs psycopg 3); psycopg2-binary is the declared dependency.
if url.startswith("postgresql://") or url.startswith("postgres://"):
    url = "postgresql+psycopg2://" + url.split("://", 1)[1]
config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True,
                      dialect_opts={"paramstyle": "named"}, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(config.get_section(config.config_ini_section, {}),
                                     prefix="sqlalchemy.", poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata,
                          compare_type=True, render_as_batch=connection.dialect.name == "sqlite")
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
