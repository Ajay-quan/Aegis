"""Response models. Unknown fields are kept (forward compatible with newer servers)."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class _Model(BaseModel):
    model_config = ConfigDict(extra="allow")


class WriteResult(_Model):
    memory_id: str
    user_id: str
    memory_type: str
    importance_score: float
    content_preview: str
    created_at: datetime
    status: str = "active"
    quarantine_reason: str | None = None
    trust: float | None = None

    @property
    def quarantined(self) -> bool:
        return self.status == "pending"


class Memory(_Model):
    memory_id: str
    content: str
    memory_type: str
    importance_score: float
    semantic_score: float
    composite_score: float
    rank: int
    created_at: datetime


class RetrieveResult(_Model):
    retrieval_id: str
    query: str
    results: list[Memory]
    total_found: int
    latency_ms: float
    context_window: str = ""
    guard_report: list[dict[str, Any]] = []


class FeedbackResult(_Model):
    accepted: int
    used: int
    learning_active: bool
    weights: dict[str, float]


class HandoffPacket(_Model):
    user_id: str
    token_budget: int
    tokens_used: int
    sections: dict[str, list[dict[str, Any]]]
    omitted: dict[str, int] = {}
    markdown: str


class ErasureReceipt(_Model):
    body: dict[str, Any]
    signature: str
    alg: str

    @property
    def receipt_id(self) -> str:
        return self.body["receipt_id"]

    @property
    def verified(self) -> bool:
        return bool(self.body.get("verified"))


class CorrectionResult(_Model):
    corrected_memory_id: str
    replacement_memory_id: str | None
    kind: str
    source_trust_after: float | None
    flagged_derived: list[str]
    receipt_id: str | None = None


class QuarantineItem(_Model):
    memory_id: str
    content: str
    reason: str
    trust: float
    source: str
    created_at: datetime
