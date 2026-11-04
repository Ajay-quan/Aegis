"""Outcome capture: corrections, confirmations and quarantine reviews.

These are the moments when a human tells the system whether a memory was right. Each one:
  1. fixes the memory itself (supersede, activate, or erase), and
  2. teaches the TrustCalibrator how reliable that memory's source/origin is.

Corrections distinguish three kinds, because they are different evidence:
  * ``wrong``      the memory was never true    -> source/origin penalised
  * ``outdated``   it was true but has changed  -> no penalty (the user moved; the CRM wasn't wrong)
  * ``malicious``  an attack that slipped past quarantine -> origin penalised as a rejection,
                   risk model trained on it (this is how recall improves), and the memory plus
                   everything derived from it is erased with a receipt

Either way, memories *derived* from the corrected one (reflections, summaries, merges) are flagged
as suspect and returned as the correction's blast radius, so stale conclusions don't outlive the fact.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from core.schemas.memory import ContradictionStatus, SourceType
from domain.integrity.provenance import derived_from
from domain.learning.trust_calibrator import memory_source_origin

logger = logging.getLogger(__name__)

CORRECTION_KINDS = ("wrong", "outdated", "malicious")


class OutcomeError(ValueError):
    pass


def _val(v: Any) -> str:
    return v.value if hasattr(v, "value") else str(v)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class OutcomeService:
    def __init__(
        self,
        relational_store: Any,
        vector_store: Any,
        ingest_service: Any,
        trust_calibrator: Any,
        erasure_service: Any | None = None,
        risk_model: Any | None = None,
    ) -> None:
        self._db = relational_store
        self._vs = vector_store
        self._ingest = ingest_service
        self._cal = trust_calibrator
        self._erase = erasure_service
        self._risk = risk_model

    async def _train_risk(self, m: Any, malicious: bool, missed: bool = False) -> None:
        if self._risk is None:
            return
        held_by_model = (m.metadata.get("quarantine") or {}).get("trigger") == "model"
        await self._risk.learn(m.content, malicious=malicious, held_by_model=held_by_model, missed=missed)

    async def _owned(self, memory_id: str, user_id: str, status: str | None = None) -> Any:
        try:
            m = await self._db.get_memory(memory_id)
        except Exception:
            raise OutcomeError("memory not found")
        if m.user_id != user_id:
            raise OutcomeError("memory not found")  # don't leak existence across users
        if status and _val(m.status) != status:
            raise OutcomeError(f"memory is {_val(m.status)}, expected {status}")
        return m

    async def _learn(self, m: Any, event: str) -> float | None:
        if "provenance" not in m.metadata:
            return None
        source, origin = memory_source_origin(m.metadata, m.source_type)
        return await self._cal.record(source, origin, event)

    # ------------------------------------------------------------------
    # Corrections
    # ------------------------------------------------------------------

    async def correct(
        self,
        user_id: str,
        memory_id: str,
        kind: str,
        corrected_text: str = "",
        note: str = "",
    ) -> dict[str, Any]:
        if kind not in CORRECTION_KINDS:
            raise OutcomeError(f"kind must be one of {CORRECTION_KINDS}")
        old = await self._owned(memory_id, user_id, status="active")
        if kind == "malicious":
            return await self._report_missed_attack(old, note)

        replacement = None
        if corrected_text.strip():
            replacement = await self._ingest.ingest_text(
                text=corrected_text.strip(),
                user_id=user_id,
                agent_id=old.agent_id,
                memory_type=old.memory_type,
                source_type=SourceType.USER_MESSAGE,
                metadata={"provenance": {"origin": "correction"}, "corrects": old.memory_id},
                importance_override=max(old.importance_score, 0.6),
            )

        old.status = "superseded"
        old.metadata["correction"] = {"kind": kind, "note": note, "at": _now()}
        if replacement is not None:
            old.metadata["superseded_by"] = replacement.memory_id
        await self._db.update_memory(old)
        await self._vs.update_payload(old.memory_id, {"status": "superseded"})

        learned = await self._learn(old, "corrected") if kind == "wrong" else None
        blast = await self._flag_derived(old)

        return {
            "corrected_memory_id": old.memory_id,
            "replacement_memory_id": replacement.memory_id if replacement else None,
            "kind": kind,
            "source_trust_after": learned,
            "flagged_derived": blast,
        }

    async def _report_missed_attack(self, m: Any, note: str) -> dict[str, Any]:
        learned = await self._learn(m, "quarantine_rejected")
        await self._train_risk(m, malicious=True, missed=True)  # before erasure; content is gone after
        receipt = None
        if self._erase is not None:
            receipt = await self._erase.forget(
                user_id=m.user_id, memory_ids=[m.memory_id], include_duplicates=True,
                reason=f"reported as malicious: {note}".strip(": "),
            )
        erased = [e["memory_id"] for e in receipt["body"]["erased"]] if receipt else []
        return {
            "corrected_memory_id": m.memory_id,
            "replacement_memory_id": None,
            "kind": "malicious",
            "source_trust_after": learned,
            "flagged_derived": [i for i in erased if i != m.memory_id],
            "receipt_id": receipt["body"]["receipt_id"] if receipt else None,
        }

    async def _flag_derived(self, root: Any) -> list[str]:
        """Mark active memories derived (transitively) from ``root`` as suspect."""
        active = await self._db.list_memories(user_id=root.user_id, status="active", limit=1000)
        tainted, flagged = {root.memory_id}, []
        changed = True
        while changed:
            changed = False
            for m in active:
                if m.memory_id in tainted:
                    continue
                if tainted & (set(derived_from(m.metadata)) | set(m.parent_memory_ids)):
                    tainted.add(m.memory_id)
                    m.contradiction_status = ContradictionStatus.SUSPECTED
                    m.confidence_score = round(m.confidence_score * 0.5, 4)
                    m.metadata["derived_from_corrected"] = root.memory_id
                    await self._db.update_memory(m)
                    flagged.append(m.memory_id)
                    changed = True
        return flagged

    async def confirm(self, user_id: str, memory_id: str) -> dict[str, Any]:
        m = await self._owned(memory_id, user_id, status="active")
        m.confidence_score = min(1.0, m.confidence_score + 0.1)
        m.metadata["confirmed_at"] = _now()
        await self._db.update_memory(m)
        await self._train_risk(m, malicious=False)
        return {"memory_id": memory_id, "source_trust_after": await self._learn(m, "confirmed")}

    # ------------------------------------------------------------------
    # Quarantine review
    # ------------------------------------------------------------------

    async def release(self, user_id: str, memory_id: str) -> dict[str, Any]:
        m = await self._owned(memory_id, user_id, status="pending")
        m.status = "active"
        m.metadata.setdefault("quarantine", {})["released_at"] = _now()
        await self._db.update_memory(m)
        await self._vs.update_payload(memory_id, {"status": "active"})
        await self._train_risk(m, malicious=False)
        return {
            "memory_id": memory_id,
            "status": "active",
            "source_trust_after": await self._learn(m, "quarantine_released"),
        }

    async def reject(self, user_id: str, memory_id: str) -> dict[str, Any]:
        """Reject held content: learn from it, then erase it with a receipt."""
        m = await self._owned(memory_id, user_id, status="pending")
        learned = await self._learn(m, "quarantine_rejected")
        await self._train_risk(m, malicious=True)  # train before erasure; content is gone after
        receipt = None
        if self._erase is not None:
            receipt = await self._erase.forget(
                user_id=user_id, memory_ids=[memory_id], include_duplicates=False,
                reason="quarantine rejected by reviewer",
            )
        return {
            "memory_id": memory_id,
            "status": "erased" if receipt else "rejected",
            "source_trust_after": learned,
            "receipt_id": receipt["body"]["receipt_id"] if receipt else None,
        }
