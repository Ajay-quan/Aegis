"""Control-plane store provider (separate module to avoid auth <-> dependencies cycles)."""
from __future__ import annotations

from pathlib import Path

from adapters.relational_store.control_store import ControlStore
from core.config.settings import settings

_control_store: ControlStore | None = None


async def get_control_store() -> ControlStore:
    """Durable control plane. Production schema comes from Alembic; dev creates it on boot."""
    global _control_store
    if _control_store is None:
        url = settings.resolved_control_database_url
        if url.startswith("sqlite"):
            Path(settings.dev_control_db_path).parent.mkdir(parents=True, exist_ok=True)
        store = ControlStore(url)
        if not settings.is_production_like:
            await store.create_schema()
        _control_store = store
    return _control_store


