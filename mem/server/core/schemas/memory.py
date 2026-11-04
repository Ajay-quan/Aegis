"""Core Pydantic v2 schemas for AegisMem memory objects."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_id() -> str:
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class MemoryType(str, Enum):
    OBSERVATION = "observation"
    FACT = "fact"
    EPISODE = "episode"
    PROCEDURE = "procedure"
    REFLECTION = "reflection"
    WORKING = "working"
    SUMMARY = "summary"


class MemoryStatus(str, Enum):
    ACTIVE = "active"
    SUPERSEDED = "superseded"
    ARCHIVED = "archived"
    DELETED = "deleted"
    PENDING = "pending"


class SourceType(str, Enum):
    USER_MESSAGE = "user_message"
    AGENT_OBSERVATION = "agent_observation"
    TOOL_OUTPUT = "tool_output"
    REFLECTION = "reflection"
    INGESTION = "ingestion"
    SYSTEM = "system"


class ContradictionStatus(str, Enum):
    NONE = "none"
    SUSPECTED = "suspected"
    CONFIRMED = "confirmed"
    RESOLVED = "resolved"


class ContradictionType(str, Enum):
    DIRECT_CONFLICT = "direct_conflict"
    PREFERENCE_CHANGE = "preference_change"
    TEMPORAL_UPDATE = "temporal_update"
    NONE = "none"


class MemoryLayer(str, Enum):
    EPISODIC = "episodic"    # Raw user events, conversational observations
    SEMANTIC = "semantic"    # Stable consolidated facts, preferences, profiles


class ImportanceLevel(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    TRIVIAL = "trivial"


# ---------------------------------------------------------------------------
# Base Memory Item
# ---------------------------------------------------------------------------


class MemoryItem(BaseModel):
    """The canonical memory record. Every memory in AegisMem is a MemoryItem."""

    memory_id: str = Field(default_factory=new_id)
    tenant_id: str = Field(default="default", description="Owning tenant (isolation boundary)")
    namespace: str = Field(..., description="Logical partition (e.g. 'user:123:agent:chat')")
    user_id: str = Field(..., description="Owner user identifier")
    agent_id: str = Field(default="", description="Agent that created this memory")
    memory_type: MemoryType = MemoryType.OBSERVATION
    memory_layer: MemoryLayer = MemoryLayer.EPISODIC
    content: str = Field(..., min_length=1, description="Textual content of the memory")
    content_embedding: list[float] | None = Field(default=None, exclude=True)

    # Source tracking
    source_type: SourceType = SourceType.USER_MESSAGE
    source_ref: str = Field(default="", description="Reference to source (session_id, message_id)")

    # Temporal fields
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
    event_time: datetime | None = Field(default=None, description="When the event occurred")
    valid_from: datetime | None = None
    valid_to: datetime | None = None

    # Scoring fields
    importance_score: float = Field(default=0.5, ge=0.0, le=1.0)
    recency_score: float = Field(default=1.0, ge=0.0, le=1.0)
    confidence_score: float = Field(default=0.8, ge=0.0, le=1.0)
    access_count: int = Field(default=0, ge=0)

    # Retrieval feedback
    retrieval_count: int = Field(default=0, ge=0)
    successful_retrieval_count: int = Field(default=0, ge=0)

    # Versioning
    version: int = Field(default=1, ge=1)
    parent_memory_ids: list[str] = Field(default_factory=list)

    # Status
    status: MemoryStatus = MemoryStatus.ACTIVE
    contradiction_status: ContradictionStatus = ContradictionStatus.NONE
    contradicted_by: list[str] = Field(default_factory=list, description="IDs of memories that contradict this one")

    # Flexible metadata
    metadata: dict[str, Any] = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list)

    @field_validator("namespace")
    @classmethod
    def validate_namespace(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("namespace cannot be empty")
        return v.strip()

    def bump_access(self) -> "MemoryItem":
        # Access is not a modification: touching updated_at here made every retrieval
        # look "recent" to the ranking (a popularity loop through recency).
        self.access_count += 1
        return self

    def supersede(self) -> "MemoryItem":
        self.status = MemoryStatus.SUPERSEDED
        self.updated_at = utcnow()
        return self

    model_config = {"use_enum_values": True}


# ---------------------------------------------------------------------------
# Observation
# ---------------------------------------------------------------------------


class Observation(BaseModel):
    """A raw observation from a conversation or tool output."""

    observation_id: str = Field(default_factory=new_id)
    session_id: str
    user_id: str
    agent_id: str = ""
    content: str
    source_type: SourceType = SourceType.USER_MESSAGE
    observed_at: datetime = Field(default_factory=utcnow)
    metadata: dict[str, Any] = Field(default_factory=dict)
    processed: bool = False


# ---------------------------------------------------------------------------
# Reflection
# ---------------------------------------------------------------------------


class Reflection(BaseModel):
    """Higher-level synthesis derived from multiple observations/memories."""

    reflection_id: str = Field(default_factory=new_id)
    user_id: str
    agent_id: str = ""
    namespace: str
    content: str
    derivation_ids: list[str] = Field(default_factory=list, description="Source memory IDs")
    confidence: float = Field(default=0.7, ge=0.0, le=1.0)
    refresh_after: int = Field(default=10, description="Refresh after N new observations")
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
    version: int = 1


# ---------------------------------------------------------------------------
# Fact Record
# ---------------------------------------------------------------------------


class FactRecord(BaseModel):
    """A discrete, verifiable fact about a user or domain."""

    fact_id: str = Field(default_factory=new_id)
    user_id: str
    agent_id: str = ""
    namespace: str
    subject: str = Field(..., description="Entity this fact is about")
    predicate: str = Field(..., description="Relationship or attribute name")
    obj: str = Field(..., alias="object", description="Value or target entity")
    confidence: float = Field(default=0.9, ge=0.0, le=1.0)
    source_memory_ids: list[str] = Field(default_factory=list)
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
    status: MemoryStatus = MemoryStatus.ACTIVE

    model_config = {"populate_by_name": True}


# ---------------------------------------------------------------------------
# Retrieval
# ---------------------------------------------------------------------------


class RetrievalQuery(BaseModel):
    """A structured memory retrieval request."""

    query_text: str
    user_id: str
    agent_id: str = ""
    namespace: str = ""
    memory_types: list[MemoryType] = Field(default_factory=list)
    memory_layers: list[MemoryLayer] = Field(default_factory=list, description="Filter by memory layer")
    top_k: int = Field(default=5, ge=1, le=50)
    min_importance: float = Field(default=0.0, ge=0.0, le=1.0)
    time_range_start: datetime | None = None
    time_range_end: datetime | None = None
    include_archived: bool = False
    filters: dict[str, Any] = Field(default_factory=dict)


class RetrievalCandidate(BaseModel):
    """A memory candidate returned during retrieval with composite score."""

    memory: MemoryItem
    semantic_score: float = Field(ge=0.0, le=1.0)
    recency_score: float = Field(ge=0.0, le=1.0)
    importance_score: float = Field(ge=0.0, le=1.0)
    lexical_score: float = Field(default=0.0, ge=0.0, le=1.0)
    exact_match_bonus: float = Field(default=0.0, ge=0.0, le=1.0)
    composite_score: float = Field(ge=0.0, le=1.0)
    rank: int = 0


class RetrievalResult(BaseModel):
    """Final retrieval result set."""

    retrieval_id: str = Field(default_factory=new_id)
    query: RetrievalQuery
    candidates: list[RetrievalCandidate]
    total_found: int
    guard_report: list[dict[str, Any]] = Field(
        default_factory=list, description="Candidates withheld or replaced by the integrity guard",
    )
    retrieved_at: datetime = Field(default_factory=utcnow)
    latency_ms: float = 0.0
    # Correlation id for the AegisMem-CL feedback loop: clients echo this back to
    # POST /feedback so served candidates become labeled training examples.
    # Empty when continual learning is disabled.
    query_id: str = ""


# ---------------------------------------------------------------------------
# Contradiction
# ---------------------------------------------------------------------------


class ContradictionReport(BaseModel):
    """Report of a detected contradiction between two memories."""

    report_id: str = Field(default_factory=new_id)
    memory_a_id: str
    memory_b_id: str
    contradiction_description: str
    contradiction_type: ContradictionType = ContradictionType.NONE
    confidence: float = Field(ge=0.0, le=1.0)
    detected_at: datetime = Field(default_factory=utcnow)
    resolved: bool = False
    resolution_note: str = ""
    resolved_at: datetime | None = None


# ---------------------------------------------------------------------------
# Memory Update Decision
# ---------------------------------------------------------------------------


class MemoryUpdateDecision(BaseModel):
    """Decision record for a memory update operation."""

    decision_id: str = Field(default_factory=new_id)
    existing_memory_id: str
    new_content: str
    action: str = Field(..., description="create | update | merge | supersede | skip")
    reason: str = ""
    confidence: float = Field(default=0.8, ge=0.0, le=1.0)
    decided_at: datetime = Field(default_factory=utcnow)
    applied: bool = False


# ---------------------------------------------------------------------------
# Working Memory
# ---------------------------------------------------------------------------


class WorkingMemory(BaseModel):
    """Transient in-context memory for an active agent session."""

    session_id: str
    agent_id: str
    user_id: str
    current_task: str = ""
    current_plan: list[str] = Field(default_factory=list)
    recent_tool_outputs: list[dict[str, Any]] = Field(default_factory=list)
    pinned_memories: list[MemoryItem] = Field(default_factory=list)
    conversation_turns: list[dict[str, str]] = Field(default_factory=list)
    token_budget: int = 4096
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)

    def add_turn(self, role: str, content: str) -> None:
        self.conversation_turns.append({"role": role, "content": content})
        self.updated_at = utcnow()

    def add_tool_output(self, tool_name: str, output: Any) -> None:
        self.recent_tool_outputs.append({"tool": tool_name, "output": str(output)})
        if len(self.recent_tool_outputs) > 20:
            self.recent_tool_outputs = self.recent_tool_outputs[-20:]
        self.updated_at = utcnow()
