# SPDX-License-Identifier: FSL-1.1-ALv2
# Copyright 2026 AegisTrace contributors
from aegistrace.evidence.events import ChainBuilder, genesis_hash


def _chain(tenant="t", run="r"):
    c = ChainBuilder(tenant, "p", run)
    c.append(
        event_id="e1",
        event_type="x",
        actor_id="a",
        correlation_id="c",
        timestamp="2026-01-01T00:00:00Z",
        payload={"k": 1},
    )
    return c


def test_genesis_binds_tenant_and_run():
    assert genesis_hash("t1", "r") != genesis_hash("t2", "r")
    assert genesis_hash("t", "r1") != genesis_hash("t", "r2")


def test_identical_content_in_other_run_hashes_differently():
    assert _chain(run="r1").head != _chain(run="r2").head
    assert _chain(tenant="t1").head != _chain(tenant="t2").head


def test_hash_is_deterministic():
    assert _chain().head == _chain().head
