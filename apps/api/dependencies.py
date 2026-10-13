"""Dependency injection for FastAPI - wires up all services."""
from __future__ import annotations

import logging
from functools import lru_cache
from typing import Annotated

from fastapi import Depends

from core.config import settings
from adapters.embeddings.backend import get_embedding_backend, EmbeddingBackend
from adapters.llm.factory import create_llm_client
from adapters.llm.base import LLMClient
from adapters.vector_store.qdrant_store import InMemoryVectorStore, QdrantStore
from adapters.graph_store.neo4j_store import MockGraphStore, GraphStore
from adapters.relational_store.postgres_store import PostgresStore
from services.ingest_service import IngestionService
from services.retrieve_service import RetrievalService
from services.update_service import UpdateService
from services.reflect_service import ReflectionService
from services.contradiction_service import ContradictionService
from pathlib import Path

from adapters.relational_store.control_store import ControlStore
from adapters.graph_store.null_store import NullGraphStore
from adapters.vector_store.pgvector_store import PgVectorStore
from adapters.tenancy import TenantScopedMemoryStore, TenantScopedVectorStore
from apps.api.auth import Principal, get_principal
from apps.api.control import get_control_store  # noqa: F401  (re-exported for overrides)
from services.feedback_service import FeedbackService, SqlRetrievalLedger
from services.handoff_service import HandoffService
from services.erasure_service import ErasureService, SqlReceiptStore
from services.learning_runtime import LearningRuntime
from services.vector_sync import ResilientVectorStore
from domain.learning import OnlineWeightLearner
from domain.learning.trust_calibrator import TrustCalibrator
from domain.learning.risk_model import OnlineRiskModel
from services.guard_service import MemoryGuard
from services.outcome_service import OutcomeService

logger = logging.getLogger(__name__)

# Global singletons (initialized at startup)
_db_store: PostgresStore | None = None
_vector_store: InMemoryVectorStore | None = None
_graph_store: MockGraphStore | None = None

_runtime: LearningRuntime | None = None


async def get_runtime(
    control: Annotated[ControlStore, Depends(get_control_store)],
) -> LearningRuntime:
    global _runtime
    if _runtime is None:
        _runtime = LearningRuntime(control, hash_secret=settings.app_secret_key)
    return _runtime


async def get_tenant_id(principal: Annotated[Principal, Depends(get_principal)]) -> str:
    """Tenant of the authenticated caller; the isolation boundary for every store."""
    return principal.tenant_id


async def get_calibrator(
    tenant: Annotated[str, Depends(get_tenant_id)],
    runtime: Annotated[LearningRuntime, Depends(get_runtime)],
) -> TrustCalibrator:
    return await runtime.trust(tenant)


async def get_risk_model(
    tenant: Annotated[str, Depends(get_tenant_id)],
    runtime: Annotated[LearningRuntime, Depends(get_runtime)],
) -> OnlineRiskModel:
    return await runtime.risk(tenant)


async def get_learner(
    tenant: Annotated[str, Depends(get_tenant_id)],
    runtime: Annotated[LearningRuntime, Depends(get_runtime)],
) -> OnlineWeightLearner:
    return runtime.weight_learner(tenant)


async def get_ledger(
    tenant: Annotated[str, Depends(get_tenant_id)],
    control: Annotated[ControlStore, Depends(get_control_store)],
) -> SqlRetrievalLedger:
    return SqlRetrievalLedger(control, tenant)


async def get_receipt_store(
    tenant: Annotated[str, Depends(get_tenant_id)],
    control: Annotated[ControlStore, Depends(get_control_store)],
) -> SqlReceiptStore:
    return SqlReceiptStore(control, tenant)


async def get_raw_db_store() -> PostgresStore:
    global _db_store
    if _db_store is None and settings.memory_backend == "memory":
        if settings.is_production_like:
            raise RuntimeError("memory_backend=memory is not allowed in staging/production")
        from adapters.relational_store.memory_store import InMemoryMemoryStore
        logger.warning("Using in-memory memory store: nothing persists across restarts")
        _db_store = InMemoryMemoryStore()  # type: ignore
    if _db_store is None:
        store = PostgresStore(settings.postgres_url)
        try:
            await store.initialize()
        except Exception as e:
            if settings.is_production_like:
                raise RuntimeError(f"Postgres unavailable in {settings.app_env}: {e}") from e
            from adapters.relational_store.memory_store import InMemoryMemoryStore
            logger.warning(f"Postgres unavailable ({e}); DEVELOPMENT fallback to in-memory store")
            _db_store = InMemoryMemoryStore()  # type: ignore
            return _db_store
        _db_store = store
    return _db_store


async def get_raw_vector_store() -> InMemoryVectorStore:
    global _vector_store
    if _vector_store is None:
        backend = settings.vector_backend
        if backend == "pgvector":
            store = PgVectorStore(settings.postgres_url)
            await store.initialize(settings.vector_dimension)
            _vector_store = store  # type: ignore
            logger.info("Using pgvector (single-store mode)")
            return _vector_store
        if backend == "memory":
            if settings.is_production_like:
                raise RuntimeError("vector_backend=memory is not allowed in staging/production")
            store = InMemoryVectorStore()
            await store.initialize(settings.vector_dimension)
            _vector_store = store
            return _vector_store
        # Try Qdrant first, fall back to in-memory (development only)
        try:
            qdrant = QdrantStore(
                host=settings.qdrant_host,
                port=settings.qdrant_port,
                collection_name=settings.qdrant_collection,
            )
            await qdrant.initialize(settings.embedding_dimension)
            _vector_store = qdrant  # type: ignore
            logger.info("Using Qdrant vector store")
        except Exception as e:
            if settings.is_production_like:
                # Fail closed: an in-memory index would silently lose writes on restart.
                raise RuntimeError(f"Qdrant unavailable in {settings.app_env}: {e}") from e
            logger.warning(f"Qdrant unavailable ({e}), using in-memory vector store")
            store = InMemoryVectorStore()
            await store.initialize(settings.embedding_dimension)
            _vector_store = store
    return _vector_store


async def get_graph_store() -> MockGraphStore:
    global _graph_store
    if _graph_store is None and settings.graph_backend == "none":
        _graph_store = NullGraphStore()  # type: ignore
    if _graph_store is None and settings.graph_backend == "memory":
        if settings.is_production_like:
            raise RuntimeError("graph_backend=memory is not allowed in staging/production")
        _graph_store = MockGraphStore()
    if _graph_store is None:
        try:
            from adapters.graph_store.neo4j_store import GraphStore as Neo4jStore
            store = Neo4jStore(
                uri=settings.neo4j_uri,
                user=settings.neo4j_user,
                password=settings.neo4j_password,
            )
            await store.connect()
            _graph_store = store  # type: ignore
            logger.info("Using Neo4j graph store")
        except Exception as e:
            if settings.is_production_like:
                raise RuntimeError(f"Neo4j unavailable in {settings.app_env}: {e}") from e
            logger.warning(f"Neo4j unavailable ({e}), using mock graph store")
            mock = MockGraphStore()
            await mock.connect()
            _graph_store = mock
    return _graph_store


async def get_db_store(
    raw: Annotated[PostgresStore, Depends(get_raw_db_store)],
    tenant: Annotated[str, Depends(get_tenant_id)],
) -> TenantScopedMemoryStore:
    """Every service and route sees only the caller's tenant."""
    return TenantScopedMemoryStore(raw, tenant)


async def get_vector_store(
    raw: Annotated[InMemoryVectorStore, Depends(get_raw_vector_store)],
    tenant: Annotated[str, Depends(get_tenant_id)],
    control: Annotated[ControlStore, Depends(get_control_store)],
) -> TenantScopedVectorStore:
    return TenantScopedVectorStore(ResilientVectorStore(raw, control, tenant), tenant)


def get_embedding() -> EmbeddingBackend:
    """Configured embedding backend. Never silently degrades: mock is development-only."""
    return get_embedding_backend(
        settings.embedding_backend, settings.embedding_model, settings.embedding_dimension,
        settings.embedding_api_base, settings.embedding_api_key or settings.openai_api_key,
    )


def get_llm() -> LLMClient:
    """Configured LLM. Never silently substitutes a fake: mock only when explicitly configured
    (development/tests); otherwise an unavailable client whose every call raises (HTTP 503)."""
    if settings.default_llm_provider == "mock":
        from adapters.llm.mock_client import MockLLMClient
        return MockLLMClient()
    try:
        return create_llm_client()
    except Exception as e:
        logger.error(f"LLM client unavailable ({e}); LLM-dependent endpoints will return 503")
        from adapters.llm.unavailable import UnavailableLLMClient
        return UnavailableLLMClient(str(e))


async def get_ingest_service(
    db: Annotated[PostgresStore, Depends(get_db_store)],
    vs: Annotated[InMemoryVectorStore, Depends(get_vector_store)],
    graph: Annotated[MockGraphStore, Depends(get_graph_store)],
    cal: Annotated[TrustCalibrator, Depends(get_calibrator)],
    risk: Annotated[OnlineRiskModel, Depends(get_risk_model)],
) -> IngestionService:
    return IngestionService(
        relational_store=db,
        vector_store=vs,
        embedding_backend=get_embedding(),
        graph_store=graph,
        llm_client=get_llm(),
        trust_calibrator=cal,
        risk_model=risk,
    )


async def get_retrieve_service(
    db: Annotated[PostgresStore, Depends(get_db_store)],
    vs: Annotated[InMemoryVectorStore, Depends(get_vector_store)],
    cal: Annotated[TrustCalibrator, Depends(get_calibrator)],
    learner: Annotated[OnlineWeightLearner, Depends(get_learner)],
    ledger: Annotated[SqlRetrievalLedger, Depends(get_ledger)],
) -> RetrievalService:
    return RetrievalService(
        relational_store=db,
        vector_store=vs,
        embedding_backend=get_embedding(),
        learner=learner,
        ledger=ledger,
        guard=MemoryGuard(db, trust_calibrator=cal),
    )


async def get_update_service(
    db: Annotated[PostgresStore, Depends(get_db_store)],
    vs: Annotated[InMemoryVectorStore, Depends(get_vector_store)],
    ingest: Annotated[IngestionService, Depends(get_ingest_service)],
) -> UpdateService:
    return UpdateService(
        relational_store=db,
        vector_store=vs,
        embedding_backend=get_embedding(),
        llm_client=get_llm(),
        ingest_service=ingest,
    )


async def get_reflect_service(
    db: Annotated[PostgresStore, Depends(get_db_store)],
    ingest: Annotated[IngestionService, Depends(get_ingest_service)],
) -> ReflectionService:
    return ReflectionService(
        relational_store=db,
        ingest_service=ingest,
        llm_client=get_llm(),
    )


async def get_contradiction_service(
    db: Annotated[PostgresStore, Depends(get_db_store)],
    vs: Annotated[InMemoryVectorStore, Depends(get_vector_store)],
    graph: Annotated[MockGraphStore, Depends(get_graph_store)],
) -> ContradictionService:
    return ContradictionService(
        relational_store=db,
        vector_store=vs,
        embedding_backend=get_embedding(),
        llm_client=get_llm(),
        graph_store=graph,
    )


async def get_feedback_service(
    db: Annotated[PostgresStore, Depends(get_db_store)],
    cal: Annotated[TrustCalibrator, Depends(get_calibrator)],
    learner: Annotated[OnlineWeightLearner, Depends(get_learner)],
    ledger: Annotated[SqlRetrievalLedger, Depends(get_ledger)],
    risk: Annotated[OnlineRiskModel, Depends(get_risk_model)],
) -> FeedbackService:
    return FeedbackService(
        relational_store=db, ledger=ledger, learner=learner,
        trust_calibrator=cal, risk_model=risk,
    )


async def get_handoff_service(
    db: Annotated[PostgresStore, Depends(get_db_store)],
    retrieve: Annotated[RetrievalService, Depends(get_retrieve_service)],
) -> HandoffService:
    return HandoffService(relational_store=db, retrieval_service=retrieve)


async def get_erasure_service(
    db: Annotated[PostgresStore, Depends(get_db_store)],
    vs: Annotated[InMemoryVectorStore, Depends(get_vector_store)],
    graph: Annotated[MockGraphStore, Depends(get_graph_store)],
    receipts: Annotated[SqlReceiptStore, Depends(get_receipt_store)],
) -> ErasureService:
    return ErasureService(
        relational_store=db,
        vector_store=vs,
        embedding_backend=get_embedding(),
        graph_store=graph,
        receipt_store=receipts,
    )


async def get_outcome_service(
    db: Annotated[PostgresStore, Depends(get_db_store)],
    vs: Annotated[InMemoryVectorStore, Depends(get_vector_store)],
    ingest: Annotated[IngestionService, Depends(get_ingest_service)],
    erasure: Annotated[ErasureService, Depends(get_erasure_service)],
    cal: Annotated[TrustCalibrator, Depends(get_calibrator)],
    risk: Annotated[OnlineRiskModel, Depends(get_risk_model)],
) -> OutcomeService:
    return OutcomeService(
        relational_store=db, vector_store=vs, ingest_service=ingest,
        trust_calibrator=cal, erasure_service=erasure, risk_model=risk,
    )
