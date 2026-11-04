"""Production-readiness hardening tests: stores, IDs, config, embeddings, enums."""
from __future__ import annotations

import uuid

import pytest

from adapters.vector_store.qdrant_store import point_id_for
from adapters.embeddings.backend import (
    get_embedding_backend, OpenAIEmbeddingBackend, MockEmbeddingBackend,
)
from core.exceptions import EmbeddingError
from core.config.settings import Settings, settings
from core.schemas.memory import MemoryType


# --- Qdrant deterministic point IDs -----------------------------------------

def test_point_id_is_deterministic_and_uuid():
    a = point_id_for("memory-123")
    b = point_id_for("memory-123")
    assert a == b                      # stable across calls (and processes)
    uuid.UUID(a)                       # valid UUID (raises if not)


def test_point_id_distinct_for_distinct_ids():
    assert point_id_for("m1") != point_id_for("m2")


# --- Embedding factory alignment --------------------------------------------

def test_factory_openai_backend_has_expected_dimension():
    be = get_embedding_backend("openai")
    assert isinstance(be, OpenAIEmbeddingBackend)
    assert be.dimension == 1536        # text-embedding-3-small default


def test_factory_mock_backend():
    assert isinstance(get_embedding_backend("mock"), MockEmbeddingBackend)


def test_factory_unknown_backend_raises():
    with pytest.raises(EmbeddingError):
        get_embedding_backend("voyage")   # removed/unsupported


# --- Config validation & strictness -----------------------------------------

def test_invalid_embedding_backend_rejected():
    with pytest.raises(Exception):
        Settings(embedding_backend="voyage")   # not in the Literal anymore


def test_store_selectors_default_to_memory():
    s = Settings()
    assert s.relational_store == "memory"
    assert s.vector_store == "memory"
    assert s.graph_store == "memory"


def test_strict_stores_only_in_production():
    assert Settings(app_env="development").strict_stores is False
    assert Settings(app_env="production").strict_stores is True


# --- MemoryType enum contract (guards MCP/docs drift) ------------------------

def test_memory_type_enum_contract():
    # The MCP server docs and validation advertise exactly these types.
    assert {t.value for t in MemoryType} == {
        "observation", "fact", "episode", "procedure",
        "reflection", "working", "summary",
    }
