"""FastAPI API schemas for AegisMem endpoints."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Ingest
# ---------------------------------------------------------------------------


class IngestRequest(BaseModel):
    text: str = Field(..., min_length=1)
    user_id: str
    session_id: str = ""
    agent_id: str = ""
    memory_type: str = "observation"
    source_type: str = "user_message"
    event_time: datetime | None = Field(default=None, description="When this happened (defaults to now). "
                                        "Set it when importing history so recency and time questions are correct.")
    metadata: dict[str, Any] = Field(default_factory=dict)


class IngestResponse(BaseModel):
    memory_id: str
    user_id: str
    memory_type: str
    importance_score: float
    content_preview: str
    created_at: datetime
    status: str = Field(default="active", description="'active', or 'pending' if quarantined for review")
    quarantine_reason: str | None = None
    trust: float | None = None


class BatchIngestRequest(BaseModel):
    items: list[IngestRequest]


class BatchIngestResponse(BaseModel):
    ingested: int
    failed: int
    memory_ids: list[str]


# ---------------------------------------------------------------------------
# Retrieve
# ---------------------------------------------------------------------------


class RetrieveRequest(BaseModel):
    query: str = Field(..., min_length=1)
    user_id: str
    agent_id: str = ""
    namespace: str = ""
    top_k: int = Field(default=5, ge=1, le=50)
    min_importance: float = Field(default=0.0, ge=0.0, le=1.0)
    memory_types: list[str] = Field(default_factory=list)
    time_range_start: datetime | None = None
    time_range_end: datetime | None = None
    include_archived: bool = False


class MemorySnippet(BaseModel):
    memory_id: str
    content: str
    memory_type: str
    importance_score: float
    semantic_score: float
    composite_score: float
    rank: int
    created_at: datetime


class RetrieveResponse(BaseModel):
    retrieval_id: str = ""
    query: str
    results: list[MemorySnippet]
    total_found: int
    latency_ms: float
    context_window: str = ""
    guard_report: list[dict[str, Any]] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Memory CRUD
# ---------------------------------------------------------------------------


class MemoryDetailResponse(BaseModel):
    memory_id: str
    namespace: str
    user_id: str
    agent_id: str
    memory_type: str
    content: str
    source_type: str
    created_at: datetime
    updated_at: datetime
    importance_score: float
    recency_score: float
    confidence_score: float
    access_count: int
    version: int
    status: str
    contradiction_status: str
    tags: list[str]
    metadata: dict[str, Any]


class ListMemoriesRequest(BaseModel):
    user_id: str
    namespace: str = ""
    memory_type: str = ""
    status: str = "active"
    limit: int = Field(default=20, ge=1, le=100)
    offset: int = Field(default=0, ge=0)


class UpdateRequest(BaseModel):
    user_id: str
    new_content: str
    namespace: str = ""
    agent_id: str = ""


class UpdateResponse(BaseModel):
    memory_id: str
    action: str
    reason: str
    previous_memory_id: str
    content_preview: str


# ---------------------------------------------------------------------------
# Reflection
# ---------------------------------------------------------------------------


class ReflectRequest(BaseModel):
    user_id: str
    namespace: str = ""
    agent_id: str = ""
    force: bool = False


class ReflectResponse(BaseModel):
    reflections_generated: int
    reflections: list[dict[str, Any]]


# ---------------------------------------------------------------------------
# Contradiction
# ---------------------------------------------------------------------------


class ContradictionScanRequest(BaseModel):
    memory_id: str
    user_id: str


class ContradictionScanResponse(BaseModel):
    memory_id: str
    contradictions_found: int
    reports: list[dict[str, Any]]


class ContradictionListResponse(BaseModel):
    contradictions: list[dict[str, Any]]
    total: int


# ---------------------------------------------------------------------------
# Health / Status
# ---------------------------------------------------------------------------


class HealthResponse(BaseModel):
    status: str
    version: str
    components: dict[str, str]


class StatsResponse(BaseModel):
    user_id: str
    total_memories: int
    namespaces: list[str]


# ---------------------------------------------------------------------------
# Handoff
# ---------------------------------------------------------------------------


class HandoffRequest(BaseModel):
    user_id: str
    namespace: str = ""
    task: str = Field(default="", description="What the receiving agent is about to do")
    since: datetime | None = Field(default=None, description="Only show changes/activity after this time")
    token_budget: int = Field(default=1500, ge=100, le=32000)
    max_per_section: int = Field(default=10, ge=1, le=50)


# ---------------------------------------------------------------------------
# Feedback / continual learning
# ---------------------------------------------------------------------------


class FeedbackRequest(BaseModel):
    retrieval_id: str
    user_id: str
    used_memory_ids: list[str] = Field(
        default_factory=list,
        description="Memories from this retrieval the agent actually used; the rest count as unused",
    )


class FeedbackResponse(BaseModel):
    accepted: int
    used: int
    learning_active: bool
    weights: dict[str, float]


class LearningStateResponse(BaseModel):
    user_id: str
    learning_active: bool
    events: int
    positives: int
    weights: dict[str, float]
    default_weights: dict[str, float]


# ---------------------------------------------------------------------------
# Integrity: erasure, receipts, quarantine
# ---------------------------------------------------------------------------


class ForgetRequest(BaseModel):
    user_id: str
    memory_ids: list[str] = Field(default_factory=list)
    all_for_user: bool = False
    include_duplicates: bool = True
    reason: str = Field(default="", description="e.g. 'GDPR Art.17 request #123'")


class ErasureReceipt(BaseModel):
    body: dict[str, Any]
    signature: str
    alg: str


class ReceiptVerifyResponse(BaseModel):
    valid: bool


class QuarantineItem(BaseModel):
    memory_id: str
    content: str
    reason: str
    trust: float
    source: str
    created_at: datetime


class QuarantineListResponse(BaseModel):
    items: list[QuarantineItem]
    total: int


# ---------------------------------------------------------------------------
# Continual learning from outcomes
# ---------------------------------------------------------------------------


class CorrectionRequest(BaseModel):
    user_id: str
    memory_id: str
    kind: str = Field(..., description=(
        "'wrong' (never true; penalises its origin), 'outdated' (changed; no penalty), "
        "'malicious' (attack that slipped through; trains the risk model and erases it with derivatives)"
    ))
    corrected_text: str = Field(default="", description="The right information, stored as the replacement")
    note: str = ""


class CorrectionResponse(BaseModel):
    corrected_memory_id: str
    replacement_memory_id: str | None
    kind: str
    source_trust_after: float | None
    flagged_derived: list[str]
    receipt_id: str | None = None


class TrustSource(BaseModel):
    source: str
    origin: str
    trust: float
    default_trust: float
    events: int
    updated_at: str | None


class TrustSourcesResponse(BaseModel):
    sources: list[TrustSource]
    guard_min_trust: float


class StatsResponse(BaseModel):
    user_id: str
    total_memories: int
    namespaces: list[str]
    by_type: dict[str, int] = Field(default_factory=dict)
    by_status: dict[str, int] = Field(default_factory=dict)
    avg_importance: float = 0.0
    total_access_count: int = 0
    unresolved_contradictions: int = 0
    last_memory_at: str = ""
