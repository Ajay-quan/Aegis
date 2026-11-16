# SPDX-License-Identifier: FSL-1.1-ALv2
# Copyright 2026 AegisTrace contributors
"""Contract test against a real AegisMem server: the memory tools' requests
and response parsing match the live API. Set AEGIS_TEST_MEMORY_URL (and
AEGIS_TEST_MEMORY_API_KEY if that server has auth enabled) to run it."""

from __future__ import annotations

import os
import secrets

import pytest

from aegistrace.tools.memory import (
    ForgetArgs,
    HttpMemoryClient,
    RecallArgs,
    RememberArgs,
    browse,
    register_memory_tools,
)
from aegistrace.tools.registry import ToolContext, ToolRegistry

URL = os.environ.get("AEGIS_TEST_MEMORY_URL")
pytestmark = pytest.mark.skipif(not URL, reason="AEGIS_TEST_MEMORY_URL not set")


def test_remember_recall_forget_against_live_aegismem():
    reg = ToolRegistry()
    client = HttpMemoryClient(URL or "", os.environ.get("AEGIS_TEST_MEMORY_API_KEY"))
    register_memory_tools(reg, client)
    tenant = "tnt_" + secrets.token_hex(4)
    ctx = ToolContext(tenant_id=tenant, run_id="run_contract", idempotency_key="k_" + secrets.token_hex(8))
    remember, recall, forget = (reg.get(n) for n in ("memory.remember", "memory.recall", "memory.forget"))
    assert remember and recall and forget

    stored = remember.execute(ctx, RememberArgs(subject="acme", text="Acme prefers invoices in EUR"))
    assert stored.status == "active", stored
    again = remember.execute(ctx, RememberArgs(subject="acme", text="Acme prefers invoices in EUR"))
    assert again.memory_id == stored.memory_id  # same idempotency key: no duplicate write

    listed = browse(client, tenant, "acme")
    assert [(m["memory_id"], m["run_id"]) for m in listed] == [(stored.memory_id, "run_contract")]

    found = recall.execute(ctx, RecallArgs(subject="acme", query="Acme invoices EUR"))
    assert stored.memory_id in [m.memory_id for m in found.memories]
    assert all(0 <= m.score_bp <= 10_000 for m in found.memories)

    other = ToolContext(tenant_id="tnt_other_" + secrets.token_hex(4), run_id="run_x", idempotency_key="k_x")
    assert recall.execute(other, RecallArgs(subject="acme", query="Acme invoices EUR")).memories == []

    gone = forget.execute(
        ToolContext(tenant_id=tenant, run_id="run_contract", idempotency_key="k_" + secrets.token_hex(8)),
        ForgetArgs(subject="acme", memory_ids=[stored.memory_id], reason="contract test"),
    )
    assert gone.erased == 1 and gone.verified and gone.receipt_signature
    assert recall.execute(ctx, RecallArgs(subject="acme", query="Acme invoices EUR")).memories == []
