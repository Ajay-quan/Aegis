"""The OSS audit: calibrated against a naive store, and AegisMem must pass every check."""
import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "audit"))

from aegis_audit.checks import run_checks  # noqa: E402
from aegis_audit.report import summarize, to_markdown  # noqa: E402
from aegis_audit.targets import AegisMemTarget, NaiveVectorTarget  # noqa: E402
from adapters.graph_store.neo4j_store import MockGraphStore  # noqa: E402
from adapters.relational_store.memory_store import InMemoryMemoryStore  # noqa: E402
from adapters.vector_store.qdrant_store import InMemoryVectorStore  # noqa: E402
from apps.api import dependencies as deps  # noqa: E402
from apps.api.main import app  # noqa: E402


async def test_naive_store_fails_the_expected_checks():
    results = {r.id: r.verdict for r in await run_checks(NaiveVectorTarget(), "t")}
    assert results == {"REV-1": "fail", "DEL-1": "fail", "DEL-2": "fail", "DEL-3": "fail",
                       "POI-1": "fail", "POI-2": "fail", "ISO-1": "pass"}


@pytest.fixture
async def aegis_target():
    vs = InMemoryVectorStore()
    await vs.initialize(384)
    db = InMemoryMemoryStore()
    app.dependency_overrides[deps.get_raw_db_store] = lambda: db
    app.dependency_overrides[deps.get_raw_vector_store] = lambda: vs
    app.dependency_overrides[deps.get_graph_store] = MockGraphStore
    target = AegisMemTarget("http://test", transport=httpx.ASGITransport(app=app))
    yield target
    await target.close()
    for d in (deps.get_raw_db_store, deps.get_raw_vector_store, deps.get_graph_store):
        app.dependency_overrides.pop(d, None)


async def test_aegismem_passes_every_check(aegis_target):
    results = await run_checks(aegis_target, "t")
    failing = {r.id: r.evidence for r in results if r.verdict != "pass"}
    assert not failing, failing
    summary = summarize(aegis_target.name, results)
    assert summary["score"] == "7/7" and "| **PASS** |" in to_markdown(summary)
