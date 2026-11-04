"""Handoff packets: one call gives a new agent, model or human a user's context.

A packet is a token-budgeted, cited briefing built from governed memory. Sections
are filled in priority order, so a tight budget drops low-value items first:

    1. open_questions   unresolved contradictions the next agent should ask about
    2. recent_changes   facts that replaced older versions (with the old value shown)
    3. profile          stable semantic knowledge: facts, preferences, procedures
    4. task_relevant    hybrid retrieval against the incoming task, if one is given
    5. recent_activity  newest episodic memories

The build is deterministic and makes no LLM calls, so it is cheap, fast and reproducible.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field

from core.schemas.memory import MemoryItem, RetrievalQuery

logger = logging.getLogger(__name__)

SECTION_TITLES = {
    "open_questions": "Open questions (confirm with the user before relying on these)",
    "recent_changes": "Recently changed",
    "profile": "What we know",
    "task_relevant": "Relevant to the current task",
    "recent_activity": "Recent activity",
}

_PROFILE_TYPES = {"fact", "procedure", "reflection", "summary"}
_SCAN_LIMIT = 500


def estimate_tokens(text: str) -> int:
    """Cheap, provider-agnostic estimate (~4 chars/token)."""
    return max(1, (len(text) + 3) // 4)


def _val(v: Any) -> str:
    return v.value if hasattr(v, "value") else str(v)


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


class HandoffItem(BaseModel):
    memory_id: str
    text: str
    memory_type: str
    importance: float
    updated_at: datetime
    previous: str | None = None
    conflicts_with: list[str] = Field(default_factory=list)


class HandoffPacket(BaseModel):
    user_id: str
    namespace: str = ""
    task: str = ""
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    since: datetime | None = None
    token_budget: int
    tokens_used: int = 0
    sections: dict[str, list[HandoffItem]] = Field(default_factory=dict)
    omitted: dict[str, int] = Field(default_factory=dict)
    markdown: str = ""


class HandoffService:
    def __init__(self, relational_store: Any, retrieval_service: Any | None = None) -> None:
        self._db = relational_store
        self._retrieval = retrieval_service

    async def build(
        self,
        user_id: str,
        namespace: str = "",
        task: str = "",
        since: datetime | None = None,
        token_budget: int = 1500,
        max_per_section: int = 10,
    ) -> HandoffPacket:
        active = await self._db.list_memories(
            user_id=user_id, namespace=namespace, status="active", limit=_SCAN_LIMIT,
        )
        by_id = {m.memory_id: m for m in active}
        since = _aware(since) if since else None

        candidates: dict[str, list[HandoffItem]] = {
            "open_questions": self._open_questions(active, by_id),
            "recent_changes": await self._recent_changes(active, since),
            "profile": self._profile(active),
            "task_relevant": await self._task_relevant(user_id, namespace, task),
            "recent_activity": self._recent_activity(active, since),
        }

        packet = HandoffPacket(
            user_id=user_id, namespace=namespace, task=task,
            since=since, token_budget=token_budget,
        )
        header = self._header(packet)
        used = estimate_tokens(header)
        seen: set[str] = set()

        for name, items in candidates.items():
            kept: list[HandoffItem] = []
            dropped = 0
            heading_cost = estimate_tokens(SECTION_TITLES[name]) + 2
            for item in items:
                if item.memory_id in seen:
                    continue
                if len(kept) >= max_per_section:
                    dropped += 1
                    continue
                cost = estimate_tokens(self._render_item(item)) + (0 if kept else heading_cost)
                if used + cost > token_budget:
                    dropped += 1
                    continue
                kept.append(item)
                seen.add(item.memory_id)
                used += cost
            if kept:
                packet.sections[name] = kept
            if dropped:
                packet.omitted[name] = dropped

        packet.tokens_used = used
        packet.markdown = self._render(packet, header)
        return packet

    # ------------------------------------------------------------------
    # Section builders
    # ------------------------------------------------------------------

    @staticmethod
    def _item(m: MemoryItem, **extra: Any) -> HandoffItem:
        return HandoffItem(
            memory_id=m.memory_id,
            text=m.content.strip(),
            memory_type=_val(m.memory_type),
            importance=m.importance_score,
            updated_at=_aware(m.updated_at),
            **extra,
        )

    def _open_questions(self, active: list[MemoryItem], by_id: dict[str, MemoryItem]) -> list[HandoffItem]:
        items, paired = [], set()
        flagged = [
            m for m in active
            if _val(m.contradiction_status) in ("confirmed", "suspected")
        ]
        for m in sorted(flagged, key=lambda x: _aware(x.updated_at), reverse=True):
            if m.memory_id in paired:
                continue
            others = [o for o in m.contradicted_by if o in by_id]
            paired.update(others)
            paired.add(m.memory_id)
            items.append(self._item(m, conflicts_with=[by_id[o].content.strip() for o in others]))
        return items

    async def _recent_changes(self, active: list[MemoryItem], since: datetime | None) -> list[HandoffItem]:
        changed = [m for m in active if m.parent_memory_ids]
        if since:
            changed = [m for m in changed if _aware(m.updated_at) >= since]
        changed.sort(key=lambda x: _aware(x.updated_at), reverse=True)
        items = []
        for m in changed:
            previous = None
            try:
                previous = (await self._db.get_memory(m.parent_memory_ids[0])).content.strip()
            except Exception:
                pass
            items.append(self._item(m, previous=previous))
        return items

    def _profile(self, active: list[MemoryItem]) -> list[HandoffItem]:
        stable = [
            m for m in active
            if _val(m.memory_layer) == "semantic" or _val(m.memory_type) in _PROFILE_TYPES
        ]
        stable.sort(key=lambda x: (x.importance_score, x.confidence_score), reverse=True)
        return [self._item(m) for m in stable]

    async def _task_relevant(self, user_id: str, namespace: str, task: str) -> list[HandoffItem]:
        if not task.strip() or self._retrieval is None:
            return []
        try:
            result = await self._retrieval.retrieve(RetrievalQuery(
                query_text=task, user_id=user_id, namespace=namespace, top_k=10,
            ))
        except Exception as e:
            logger.warning(f"Handoff task retrieval failed: {e}")
            return []
        return [self._item(c.memory) for c in result.candidates]

    def _recent_activity(self, active: list[MemoryItem], since: datetime | None) -> list[HandoffItem]:
        episodic = [m for m in active if _val(m.memory_layer) == "episodic"]
        if since:
            episodic = [m for m in episodic if _aware(m.created_at) >= since]
        episodic.sort(key=lambda x: _aware(x.created_at), reverse=True)
        return [self._item(m) for m in episodic]

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    @staticmethod
    def _header(p: HandoffPacket) -> str:
        lines = [f"# Context handoff for user {p.user_id}"]
        if p.task:
            lines.append(f"Task: {p.task}")
        if p.since:
            lines.append(f"Changes since: {p.since.isoformat()}")
        lines.append("Cite memories by [id] when relying on them.")
        return "\n".join(lines)

    @staticmethod
    def _render_item(item: HandoffItem) -> str:
        line = f"- {item.text} [{item.memory_id[:8]}]"
        if item.previous:
            line += f" (previously: {item.previous})"
        if item.conflicts_with:
            line += f" (conflicts with: {'; '.join(item.conflicts_with)})"
        return line

    def _render(self, p: HandoffPacket, header: str) -> str:
        parts = [header]
        for name, items in p.sections.items():
            parts.append(f"\n## {SECTION_TITLES[name]}")
            parts.extend(self._render_item(i) for i in items)
        if p.omitted:
            parts.append(
                "\n_Omitted (token budget or section cap): "
                + ", ".join(f"{k}={v}" for k, v in p.omitted.items()) + "_"
            )
        return "\n".join(parts)
