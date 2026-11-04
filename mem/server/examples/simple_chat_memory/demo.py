"""
AegisMem Simple Chat Memory Demo
==================================
Demonstrates end-to-end memory: ingest, retrieve, reflect, and show context.
Runs without any external services using mock backends.
"""
from __future__ import annotations

import asyncio
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from adapters.llm.mock_client import MockLLMClient
from adapters.embeddings.backend import MockEmbeddingBackend
from adapters.vector_store.qdrant_store import InMemoryVectorStore
from adapters.graph_store.neo4j_store import MockGraphStore
from services.ingest_service import IngestionService
from services.retrieve_service import RetrievalService
from services.reflect_service import ReflectionService
from services.update_service import UpdateService
from core.schemas.memory import RetrievalQuery, MemoryType


async def main():
    print("\n" + "=" * 60)
    print("  AegisMem - Simple Chat Memory Demo")
    print("=" * 60 + "\n")

    # -------------------------------------------------------------------
    # Setup (mock backends - no external services required)
    # -------------------------------------------------------------------
    embed = MockEmbeddingBackend(dim=384)
    vs = InMemoryVectorStore()
    await vs.initialize(dimension=384)

    graph = MockGraphStore()
    await graph.connect()

    llm = MockLLMClient()
    llm.register_response(
        "reflections",
        '{"reflections": [{"content": "User has strong interest in AI and open source development", '
        '"confidence": 0.88, "supporting_indices": [0, 1, 2]}]}'
    )
    llm.register_response(
        "action",
        '{"action": "supersede", "reason": "New location supersedes old", '
        '"merged_content": "User recently moved to Austin, Texas", "confidence": 0.92}'
    )

    # In-memory "database"
    from tests.fixtures.conftest import MockPostgresStore
    db = MockPostgresStore()

    ingest = IngestionService(
        relational_store=db,
        vector_store=vs,
        embedding_backend=embed,
        graph_store=graph,
        llm_client=llm,
    )
    retrieve = RetrievalService(
        relational_store=db,
        vector_store=vs,
        embedding_backend=embed,
    )
    update = UpdateService(
        relational_store=db,
        vector_store=vs,
        embedding_backend=embed,
        llm_client=llm,
        ingest_service=ingest,
    )
    reflect = ReflectionService(
        relational_store=db,
        ingest_service=ingest,
        llm_client=llm,
    )

    USER_ID = "demo_user"

    # -------------------------------------------------------------------
    # Step 1: Simulate a conversation - ingest observations
    # -------------------------------------------------------------------
    print("📥 Step 1: Ingesting conversation observations...\n")

    conversations = [
        "I work as a machine learning engineer at a startup in San Francisco",
        "I prefer Python for everything, especially FastAPI for backend work",
        "I'm working on a personal project to build an AI assistant for research",
        "I always use dark mode in my editor and terminal",
        "I've been learning Rust in my free time for systems programming",
        "My biggest challenge right now is scaling our training pipeline",
        "I prefer async code patterns over synchronous ones",
        "I've read most of Andrej Karpathy's blog posts about neural networks",
        "I want to eventually start my own AI company",
        "My favorite papers are Attention is All You Need and the AlphaGo paper",
    ]

    memories = []
    for text in conversations:
        mem = await ingest.ingest_text(text=text, user_id=USER_ID, session_id="session_1")
        memories.append(mem)
        print(f"  ✅ [{mem.importance_score:.2f}] {text[:70]}...")

    print(f"\n  Total memories stored: {len(memories)}")

    # -------------------------------------------------------------------
    # Step 2: Retrieve relevant context
    # -------------------------------------------------------------------
    print("\n🔍 Step 2: Retrieving relevant memories for query...\n")

    query_text = "What are the user's programming skills and career goals?"
    print(f"  Query: '{query_text}'\n")

    result = await retrieve.retrieve(
        RetrievalQuery(
            query_text=query_text,
            user_id=USER_ID,
            top_k=5,
        )
    )

    print(f"  Retrieved {len(result.candidates)} memories in {result.latency_ms:.1f}ms:\n")
    for c in result.candidates:
        print(
            f"  [{c.rank}] score={c.composite_score:.3f} "
            f"(sem={c.semantic_score:.2f}, rec={c.recency_score:.2f}, "
            f"imp={c.importance_score:.2f})"
        )
        print(f"      {c.memory.content[:80]}")
        print()

    # -------------------------------------------------------------------
    # Step 3: Memory update - user moved cities
    # -------------------------------------------------------------------
    print("✏️  Step 3: Updating memory (user moved cities)...\n")

    updated_mem, decision = await update.update_or_create(
        user_id=USER_ID,
        new_content="User recently moved to Austin, Texas from San Francisco",
    )

    print(f"  Action: {decision.action}")
    print(f"  Reason: {decision.reason}")
    print(f"  New memory: {updated_mem.content}")
    print(f"  Version: {updated_mem.version}")

    # -------------------------------------------------------------------
    # Step 4: Generate reflections
    # -------------------------------------------------------------------
    print("\n💭 Step 4: Generating reflections from memories...\n")

    reflections = await reflect.generate_reflections(
        user_id=USER_ID,
        namespace=f"user:{USER_ID}",
        agent_id="demo_agent",
    )

    if reflections:
        print(f"  Generated {len(reflections)} reflection(s):\n")
        for r in reflections:
            print(f"  🔮 [{r.confidence:.2f}] {r.content}")
            print(f"     Derived from {len(r.derivation_ids)} memories")
    else:
        print("  (No reflections generated in mock mode)")

    # -------------------------------------------------------------------
    # Step 5: Build context window for next LLM call
    # -------------------------------------------------------------------
    print("\n🪟 Step 5: Building memory context window...\n")

    context = await retrieve.get_context_window(
        user_id=USER_ID,
        query_text="Tell me about the user's technical background",
        top_k=5,
    )

    print("  Context window for LLM prompt:")
    print("  " + "-" * 50)
    if context:
        for line in context.split("\n"):
            print(f"  {line}")
    else:
        print("  (Empty context - mock mode)")

    # -------------------------------------------------------------------
    # Summary
    # -------------------------------------------------------------------
    total_in_db = len(db._memories)
    print(f"\n{'='*60}")
    print(f"  Demo Complete!")
    print(f"  Memories stored: {total_in_db}")
    print(f"  Reflections generated: {len(reflections)}")
    print(f"  Vector store entries: {len(vs._store)}")
    print(f"  Graph nodes: {len(graph._nodes)}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    asyncio.run(main())
