"""PII redaction at the ingest boundary (opt-in)."""
from adapters.embeddings.backend import MockEmbeddingBackend
from adapters.graph_store.neo4j_store import MockGraphStore
from adapters.relational_store.memory_store import InMemoryMemoryStore
from adapters.vector_store.qdrant_store import InMemoryVectorStore
from core.config.settings import settings
from services.ingest_service import IngestionService


async def _ingest(text):
    vs = InMemoryVectorStore()
    await vs.initialize(64)
    svc = IngestionService(InMemoryMemoryStore(), vs, MockEmbeddingBackend(dim=64), MockGraphStore())
    return await svc.ingest_text(text, user_id="u"), vs


async def test_redaction_is_opt_in(monkeypatch):
    monkeypatch.setattr(settings, "pii_redaction_enabled", False)
    m, _ = await _ingest("Email me at jane@example.com")
    assert "jane@example.com" in m.content


async def test_pii_never_reaches_storage_or_index(monkeypatch):
    monkeypatch.setattr(settings, "pii_redaction_enabled", True)
    m, vs = await _ingest("Email jane@example.com, card 4111 1111 1111 1111, SSN 123-45-6789")
    assert "jane@example.com" not in m.content and "4111" not in m.content and "123-45-6789" not in m.content
    assert m.metadata["pii_redacted"] and m.metadata["pii_counts"]
    assert "jane@example.com" not in (await vs.get(m.memory_id)).payload["content"]
