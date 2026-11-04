"""Request-scoped tenant context consumed by Postgres row-level security.

TenantScopedMemoryStore / TenantScopedVectorStore run every inner call inside
``tenant_context(tenant_id)``. SQL stores then issue
``set_config('app.tenant_id', <tenant>, true)`` at the start of each transaction, and RLS
policies (migration 0005) only expose rows of that tenant. Background system jobs that must
see all tenants (outbox worker, operator CLI) run inside ``system_context()``, which is explicit
and greppable. With no context at all, RLS shows nothing: fail closed.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator

_tenant: ContextVar[str | None] = ContextVar("aegis_tenant", default=None)
_bypass: ContextVar[bool] = ContextVar("aegis_rls_bypass", default=False)


def current_tenant() -> str | None:
    return _tenant.get()


def rls_bypass() -> bool:
    return _bypass.get()


@contextmanager
def tenant_context(tenant_id: str) -> Iterator[None]:
    token = _tenant.set(tenant_id)
    try:
        yield
    finally:
        _tenant.reset(token)


@contextmanager
def system_context() -> Iterator[None]:
    token = _bypass.set(True)
    try:
        yield
    finally:
        _bypass.reset(token)


async def apply_rls(session) -> None:
    """Bind the current tenant to this transaction (Postgres only; no-op elsewhere)."""
    if session.bind.dialect.name != "postgresql":
        return
    from sqlalchemy import text
    await session.execute(
        text("SELECT set_config('app.tenant_id', :t, true), set_config('app.rls_bypass', :b, true)"),
        {"t": current_tenant() or "", "b": "on" if rls_bypass() else "off"},
    )
