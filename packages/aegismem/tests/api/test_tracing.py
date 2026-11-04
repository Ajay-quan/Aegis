"""Tracing: spans are emitted, nested, propagate W3C context, and never carry content."""
import json

import pytest
from httpx import ASGITransport, AsyncClient
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from adapters.graph_store.neo4j_store import MockGraphStore
from adapters.relational_store.memory_store import InMemoryMemoryStore
from adapters.vector_store.qdrant_store import InMemoryVectorStore
from apps.api import dependencies as deps
from apps.api.main import app
from core.observability import tracing

EXPORTER = InMemorySpanExporter()


@pytest.fixture
async def client(monkeypatch):
    tracing.setup_tracing(exporter=EXPORTER)
    EXPORTER.clear()
    vs = InMemoryVectorStore()
    await vs.initialize(384)
    db = InMemoryMemoryStore()
    monkeypatch.setitem(app.dependency_overrides, deps.get_raw_db_store, lambda: db)
    monkeypatch.setitem(app.dependency_overrides, deps.get_raw_vector_store, lambda: vs)
    monkeypatch.setitem(app.dependency_overrides, deps.get_graph_store, MockGraphStore)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def test_request_and_pipeline_spans(client):
    parent = "00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01"
    secret = "User's diagnosis is hypothyroidism"
    r = await client.post("/api/v1/ingest", json={"text": secret, "user_id": "u-42"},
                          headers={"traceparent": parent})
    assert r.headers["x-trace-id"] == "0af7651916cd43dd8448eb211c80319c"  # joined the caller's trace
    await client.post("/api/v1/retrieve", json={"query": "diagnosis", "user_id": "u-42"})
    await client.post("/api/v1/forget", json={"user_id": "u-42", "all_for_user": True})

    spans = EXPORTER.get_finished_spans()
    names = {s.name for s in spans}
    assert {"POST /api/v1/ingest", "POST /api/v1/retrieve", "aegis.ingest", "aegis.retrieve",
            "aegis.erasure"} <= names
    ingest = next(s for s in spans if s.name == "aegis.ingest")
    assert ingest.attributes["aegis.write.outcome"] == "stored"
    http_ingest = next(s for s in spans if s.name == "POST /api/v1/ingest")
    assert ingest.context.trace_id == http_ingest.context.trace_id  # same trace as the request
    retrieve = next(s for s in spans if s.name == "aegis.retrieve")
    http_retrieve = next(s for s in spans if s.name == "POST /api/v1/retrieve")
    by_id = {s.context.span_id: s for s in spans}
    ancestors, node = [], retrieve
    while node.parent is not None and node.parent.span_id in by_id:
        node = by_id[node.parent.span_id]
        ancestors.append(node.context.span_id)
    assert http_retrieve.context.span_id in ancestors  # nested under the request span

    dump = json.dumps([dict(s.attributes) for s in spans])
    assert "hypothyroidism" not in dump and "u-42" not in dump
