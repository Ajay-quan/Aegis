"""Integration tests for hybrid retrieval over the zero-infra stack.

These exercise the real RetrievalService + IngestionService wired to the
in-memory relational store, in-memory vector store, and mock embeddings — i.e.
the exact path the FastAPI service runs by default. The key property under test
is the *hybrid rescue*: with non-semantic mock embeddings, a keyword-relevant
memory that dense search misses must still surface via the BM25 lexical arm.
"""
from __future__ import annotations

import pytest

from adapters.relational_store.memory_store import InMemoryRelationalStore
from adapters.vector_store.qdrant_store import InMemoryVectorStore
from adapters.embeddings.backend import get_embedding_backend
from adapters.graph_store.neo4j_store import MockGraphStore
from services.ingest_service import IngestionService
from services.retrieve_service import RetrievalService
from core.schemas.memory import RetrievalQuery


@pytest.fixture
async def stack():
    db = InMemoryRelationalStore()
    await db.initialize()
    vs = InMemoryVectorStore()
    embed = get_embedding_backend("mock")
    await vs.initialize(embed.dimension)
    graph = MockGraphStore()
    await graph.connect()
    ingest = IngestionService(
        relational_store=db, vector_store=vs, embedding_backend=embed,
        graph_store=graph, llm_client=None,
    )
    retrieve = RetrievalService(
        relational_store=db, vector_store=vs, embedding_backend=embed,
    )
    return db, ingest, retrieve


async def test_in_memory_store_crud():
    db = InMemoryRelationalStore()
    await db.initialize()
    from core.schemas.memory import MemoryItem
    m = MemoryItem(namespace="user:u1", user_id="u1", content="hello world")
    await db.save_memory(m)
    got = await db.get_memory(m.memory_id)
    assert got.content == "hello world"
    assert await db.count_memories("u1") == 1
    await db.delete_memory(m.memory_id, "u1")
    assert await db.count_memories("u1") == 0


async def test_hybrid_rescues_keyword_match(stack):
    db, ingest, retrieve = stack
    await ingest.ingest_text("Alice prefers Python and FAISS for vector search", user_id="alice")
    await ingest.ingest_text("Bob enjoys hiking and photography", user_id="alice")
    await ingest.ingest_text("Carol likes tea and gardening", user_id="alice")

    result = await retrieve.retrieve(
        RetrievalQuery(query_text="FAISS Python vector search", user_id="alice", top_k=3)
    )
    top = result.candidates[0]
    # The exact-keyword memory wins, and it won on the lexical signal (mock
    # embeddings carry no semantic meaning).
    assert "FAISS" in top.memory.content
    assert top.lexical_score > 0.0


async def test_disabling_hybrid_falls_back_to_dense(stack, monkeypatch):
    from core.config.settings import settings
    monkeypatch.setattr(settings, "hybrid_retrieval_enabled", False)
    db, ingest, retrieve = stack
    await ingest.ingest_text("The quick brown fox", user_id="u2")
    result = await retrieve.retrieve(
        RetrievalQuery(query_text="quick fox", user_id="u2", top_k=3)
    )
    # Still returns results; lexical contribution is zero in dense-only mode.
    assert len(result.candidates) >= 1
    assert all(c.lexical_score == 0.0 for c in result.candidates)
