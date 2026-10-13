"""Benchmark environment: the production service graph over in-memory backends.

Benchmarks exercise the same services, guard, tenancy wrappers and learning components the
API uses. Only storage backends are in-memory, so results measure product logic, not I/O.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from adapters.embeddings.backend import MockEmbeddingBackend
from adapters.graph_store.neo4j_store import MockGraphStore
from adapters.llm.mock_client import MockLLMClient
from adapters.relational_store.memory_store import InMemoryMemoryStore
from adapters.tenancy import TenantScopedMemoryStore, TenantScopedVectorStore
from adapters.vector_store.qdrant_store import InMemoryVectorStore
from domain.learning.risk_model import OnlineRiskModel
from domain.learning.trust_calibrator import TrustCalibrator
from services.erasure_service import ErasureService
from services.guard_service import MemoryGuard
from services.ingest_service import IngestionService
from services.outcome_service import OutcomeService
from services.retrieve_service import RetrievalService

DATASETS = Path(__file__).parent / "datasets"
TENANT = "bench"


@dataclass
class Env:
    raw_db: InMemoryMemoryStore
    raw_vs: InMemoryVectorStore
    db: TenantScopedMemoryStore
    vs: TenantScopedVectorStore
    graph: MockGraphStore
    embed: MockEmbeddingBackend
    cal: TrustCalibrator
    risk: OnlineRiskModel
    ingest: IngestionService
    retrieve: RetrievalService
    erase: ErasureService
    outcomes: OutcomeService


async def build_env(dim: int = 128) -> Env:
    raw_db, raw_vs, graph = InMemoryMemoryStore(), InMemoryVectorStore(), MockGraphStore()
    await raw_vs.initialize(dim)
    db, vs = TenantScopedMemoryStore(raw_db, TENANT), TenantScopedVectorStore(raw_vs, TENANT)
    embed = MockEmbeddingBackend(dim=dim)
    cal, risk = TrustCalibrator(), OnlineRiskModel(hash_key=b"bench")
    ingest = IngestionService(db, vs, embed, graph, MockLLMClient(), trust_calibrator=cal, risk_model=risk)
    retrieve = RetrievalService(db, vs, embed, guard=MemoryGuard(db, trust_calibrator=cal))
    erase = ErasureService(db, vs, embed, graph, signing_key="bench-key")
    outcomes = OutcomeService(db, vs, ingest, cal, erase, risk)
    return Env(raw_db, raw_vs, db, vs, graph, embed, cal, risk, ingest, retrieve, erase, outcomes)


def use_embedding(env: Env, embed) -> Env:
    """Swap one embedding backend into *every* service. Partial swaps silently break duplicate
    detection and similarity checks (found during validation), so all suites must use this."""
    env.embed = embed
    for svc in (env.ingest, env.retrieve, env.erase):
        svc._embed = embed
    return env


def load_jsonl(name: str) -> list[dict[str, Any]]:
    with open(DATASETS / name) as f:
        return [json.loads(line) for line in f if line.strip()]
