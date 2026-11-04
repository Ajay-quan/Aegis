"""Verifiable, cascading erasure ("forget") with signed receipts.

Deleting the requested row is not erasure. Personal data also lives in:
  * earlier versions of the same fact (``parent_memory_ids`` ancestors)
  * derived memories: reflections, summaries and merges built from it (descendants)
  * near-duplicate copies ingested separately ("I live in Austin" said twice)
  * the vector index and the graph

``forget`` computes that closure, hard-deletes each item from every store, then
**re-checks every store** and issues a signed receipt listing what was erased, why each
item was included, and the per-store verification result. Content is never kept; items
are fingerprinted with a keyed HMAC.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from core.config.settings import settings
from core.exceptions import MemoryNotFoundError
from core.observability.metrics import ERASED_ITEMS, ERASURES
from core.observability.tracing import tracer
from domain.integrity import receipts
from domain.integrity.provenance import derived_from

logger = logging.getLogger(__name__)

DUPLICATE_SIMILARITY = 0.95
_PAGE = 500


class ErasureError(ValueError):
    pass


class InMemoryReceiptStore:
    def __init__(self) -> None:
        self._receipts: dict[str, dict[str, Any]] = {}

    async def put(self, receipt: dict[str, Any]) -> None:
        self._receipts[receipt["body"]["receipt_id"]] = receipt

    async def get(self, receipt_id: str) -> dict[str, Any] | None:
        return self._receipts.get(receipt_id)


class SqlReceiptStore:
    """Durable, tenant-scoped receipt storage."""

    def __init__(self, store: Any, tenant_id: str) -> None:
        self._store = store
        self._tenant = tenant_id

    async def put(self, receipt: dict[str, Any]) -> None:
        await self._store.put_receipt(self._tenant, receipt)

    async def get(self, receipt_id: str) -> dict[str, Any] | None:
        return await self._store.get_receipt(self._tenant, receipt_id)


class ErasureService:
    def __init__(
        self,
        relational_store: Any,
        vector_store: Any,
        embedding_backend: Any,
        graph_store: Any | None = None,
        receipt_store: InMemoryReceiptStore | None = None,
        signing_key: str | None = None,
    ) -> None:
        self._db = relational_store
        self._vs = vector_store
        self._embed = embedding_backend
        self._graph = graph_store
        self._receipts = receipt_store or InMemoryReceiptStore()
        self._key = (signing_key or settings.app_secret_key).encode("utf-8")

    async def forget(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        """Span: aegis.erasure (counts and verification only)."""
        with tracer.start_as_current_span("aegis.erasure") as span:
            receipt = await self._forget(*args, **kwargs)
            body = receipt["body"]
            span.set_attributes({"aegis.receipt_id": body["receipt_id"], "aegis.erased": len(body["erased"]),
                                 "aegis.verified": body["verified"], "aegis.scope": body["scope"]})
            return receipt

    async def _forget(
        self,
        user_id: str,
        memory_ids: list[str] | None = None,
        all_for_user: bool = False,
        include_duplicates: bool = True,
        reason: str = "",
    ) -> dict[str, Any]:
        if not memory_ids and not all_for_user:
            raise ErasureError("specify memory_ids or all_for_user")

        universe = await self._all_memories(user_id)
        by_id = {m.memory_id: m for m in universe}

        if all_for_user:
            seeds = list(by_id)
        else:
            missing = [i for i in memory_ids if i not in by_id]
            if missing:
                raise ErasureError(f"memories not found for this user: {missing}")
            seeds = list(dict.fromkeys(memory_ids))

        relation = await self._closure(seeds, by_id, include_duplicates, user_id)

        erased = []
        for mid, rel in relation.items():
            m = by_id[mid]
            erased.append({
                "memory_id": mid,
                "relation": rel,
                "fingerprint": receipts.fingerprint(self._key, m.content),
            })
            await self._purge(mid, user_id)

        verification = await self._verify(list(relation), user_id)
        body = {
            "receipt_id": str(uuid.uuid4()),
            "user_id": user_id,
            "issued_at": datetime.now(timezone.utc).isoformat(),
            "reason": reason,
            "scope": "all_for_user" if all_for_user else "memory_ids",
            "requested": seeds,
            "erased": erased,
            "verification": verification,
            "verified": all(v["clean"] for v in verification.values()),
            "retained": ["content-free operation log entries (memory_id, operation, timestamp)"],
            "not_covered": ["database backups and snapshots (expire per backup retention policy)"],
        }
        receipt = {"body": body, "signature": receipts.sign(self._key, body), "alg": "HMAC-SHA256"}
        await self._receipts.put(receipt)
        tenant = getattr(self._db, "tenant_id", "unscoped")
        ERASURES.labels(tenant, str(body["verified"]).lower()).inc()
        for e in erased:
            ERASED_ITEMS.labels(tenant, e["relation"]).inc()
        logger.info(
            f"Erasure {body['receipt_id']} user={user_id} erased={len(erased)} verified={body['verified']}"
        )
        return receipt

    async def get_receipt(self, receipt_id: str) -> dict[str, Any] | None:
        return await self._receipts.get(receipt_id)

    def verify_receipt(self, receipt: dict[str, Any]) -> bool:
        return receipts.verify(self._key, receipt.get("body", {}), receipt.get("signature", ""))

    # ------------------------------------------------------------------

    async def _all_memories(self, user_id: str) -> list[Any]:
        out, offset = [], 0
        while True:
            page = await self._db.list_memories(
                user_id=user_id, status="", limit=_PAGE, offset=offset,
            )
            out.extend(page)
            if len(page) < _PAGE:
                return out
            offset += _PAGE

    async def _closure(
        self, seeds: list[str], by_id: dict[str, Any], include_duplicates: bool, user_id: str,
    ) -> dict[str, str]:
        relation: dict[str, str] = {s: "requested" for s in seeds}

        if include_duplicates:
            for s in seeds:
                for dup in await self._near_duplicates(by_id[s].content, user_id):
                    if dup in by_id:
                        relation.setdefault(dup, "duplicate")

        changed = True
        while changed:
            changed = False
            for mid in list(relation):
                for parent in by_id[mid].parent_memory_ids:
                    if parent in by_id and parent not in relation:
                        relation[parent] = "prior_version"
                        changed = True
            for m in by_id.values():
                if m.memory_id in relation:
                    continue
                upstream = set(m.parent_memory_ids) | set(derived_from(m.metadata))
                if upstream & relation.keys():
                    relation[m.memory_id] = "derived"
                    changed = True
        return relation

    async def _near_duplicates(self, content: str, user_id: str) -> list[str]:
        try:
            vec = await self._embed.embed_single(content)
            hits = await self._vs.search(query_vector=vec, top_k=20, filter={"user_id": user_id})
            return [h.id for h in hits if h.score >= DUPLICATE_SIMILARITY]
        except Exception as e:
            logger.warning(f"Duplicate scan failed: {e}")
            return []

    async def _purge(self, memory_id: str, user_id: str) -> None:
        await self._db.purge_memory(memory_id, user_id)
        await self._vs.delete(memory_id)
        if self._graph is not None:
            await self._graph.delete_memory_node(memory_id)

    async def _verify(self, ids: list[str], user_id: str) -> dict[str, dict[str, Any]]:
        residual: dict[str, list[str]] = {"relational": [], "vector": [], "graph": []}
        for mid in ids:
            try:
                await self._db.get_memory(mid)
                residual["relational"].append(mid)
            except MemoryNotFoundError:
                pass
            if await self._vs.get(mid) is not None:
                residual["vector"].append(mid)
            if self._graph is not None and await self._graph.has_memory_node(mid):
                residual["graph"].append(mid)
        stores = {
            name: {"checked": len(ids), "residual": r, "clean": not r}
            for name, r in residual.items()
        }
        if self._graph is None or getattr(self._graph, "configured", True) is False:
            stores["graph"] = {"checked": 0, "residual": [], "clean": True, "note": "not configured"}
        return stores
