# SPDX-License-Identifier: FSL-1.1-ALv2
# Copyright 2026 AegisTrace contributors
"""Tenant-bound transactions.

Every app-role transaction binds app.tenant_id with SET LOCAL semantics
(set_config(..., true)), so the binding cannot leak across pooled connections.
Row-level security then filters every query in that transaction.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Connection, Engine, create_engine, text

TENANT_ID = re.compile(r"\Atnt_[a-z0-9_]{1,60}\Z")


class InvalidTenant(ValueError):
    pass


def make_engine(url: str) -> Engine:
    return create_engine(url, pool_pre_ping=True, pool_size=10, max_overflow=10)


@contextmanager
def tenant_tx(engine: Engine, tenant_id: str) -> Iterator[Connection]:
    if not TENANT_ID.match(tenant_id):
        raise InvalidTenant(tenant_id)
    with engine.begin() as conn:
        conn.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": tenant_id})
        yield conn
