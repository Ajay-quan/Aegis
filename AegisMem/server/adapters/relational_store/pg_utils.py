"""Postgres helpers shared by every schema-creation path."""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncConnection


async def ensure_pgvector(conn: AsyncConnection) -> None:
    """Make sure the ``vector`` extension exists before creating tables that use it.

    Production schema comes from Alembic (migration 0003 creates the extension). This guards the
    dev/test ``create_all`` paths, which otherwise fail on a fresh database with
    ``type "vector" does not exist``. No-op on other dialects or when already installed.
    """
    if conn.dialect.name != "postgresql":
        return
    present = (await conn.exec_driver_sql(
        "SELECT 1 FROM pg_extension WHERE extname = 'vector'")).first()
    if present:
        return
    try:
        await conn.exec_driver_sql("CREATE EXTENSION IF NOT EXISTS vector")
    except Exception as e:  # typically insufficient privilege for the app role
        raise RuntimeError("pgvector extension is missing and could not be created; run "
                           "`alembic upgrade head` as the schema owner or `CREATE EXTENSION vector`") from e
