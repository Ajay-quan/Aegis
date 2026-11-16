# SPDX-License-Identifier: FSL-1.1-ALv2
# Copyright 2026 AegisTrace contributors
"""Append-only audit log of administrative actions (Studio: Settings → Audit log).

Write the entry in the same transaction as the change it records, so a change
is never saved without its audit entry. `detail` holds identifiers and
settings, never secrets or run content.
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Connection


def audit(conn: Connection, tenant_id: str, actor_id: str, action: str, target: str, detail: dict[str, Any]) -> None:
    conn.execute(
        text(
            "INSERT INTO audit_events (tenant_id, actor_id, action, target, detail) "
            "VALUES (:t, :a, :ac, :tg, CAST(:d AS jsonb))"
        ),
        {"t": tenant_id, "a": actor_id, "ac": action, "tg": target, "d": json.dumps(detail)},
    )
