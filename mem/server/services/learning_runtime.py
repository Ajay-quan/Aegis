"""Learning runtime: durable, tenant-scoped, replica-consistent learned state.

Every learning component (trust calibrator, risk model, per-user ranking weights) is a
deterministic state machine. The runtime binds each one to an append-only event stream in
the control store:

    write:  append event (gets a global seq)  ->  catch up: replay every event > last_seq
    read:   catch up, then read in-memory state

Writes are never applied locally ahead of the log, so replicas cannot diverge or double-apply
their own events: every replica applies the same events in the same order. Snapshots are a
replay cache, written every ``snapshot_every`` events, and can be dropped at any time; ``rebuild``
recomputes a component from the raw log (audit and determinism check).
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, Callable

from adapters.relational_store.control_store import ControlStore
from core.observability.metrics import LEARNING_EVENTS
from domain.learning.risk_model import COMPONENT as RISK, OnlineRiskModel
from domain.learning.trust_calibrator import COMPONENT as TRUST, TrustCalibrator
from domain.learning.weight_learner import COMPONENT_PREFIX as WEIGHTS, OnlineWeightLearner, UserWeightModel

logger = logging.getLogger(__name__)

Builder = Callable[[dict[str, Any] | None, Callable], Any]


@dataclass
class _Handle:
    component: Any
    last_seq: int = 0
    since_snapshot: int = 0
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


class LearningRuntime:
    def __init__(
        self,
        store: ControlStore,
        hash_secret: str,
        snapshot_every: int = 200,
        max_cached: int = 10_000,
    ) -> None:
        self._store = store
        self._secret = hash_secret.encode("utf-8")
        self.snapshot_every = snapshot_every
        self._max_cached = max_cached
        self._handles: OrderedDict[tuple[str, str], _Handle] = OrderedDict()
        self._create_lock = asyncio.Lock()

    # -- public accessors ----------------------------------------------

    async def trust(self, tenant_id: str) -> TrustCalibrator:
        return await self._get(tenant_id, TRUST, lambda st, j: TrustCalibrator.from_state(st, journal=j))

    async def risk(self, tenant_id: str) -> OnlineRiskModel:
        key = self._tenant_key(tenant_id)
        return await self._get(
            tenant_id, RISK, lambda st, j: OnlineRiskModel.from_state(st, hash_key=key, journal=j),
        )

    def weight_learner(self, tenant_id: str, min_events: int = 20) -> OnlineWeightLearner:
        async def resolve(user_id: str) -> UserWeightModel:
            return await self._get(
                tenant_id, f"{WEIGHTS}{user_id}",
                lambda st, j: UserWeightModel.from_state(user_id, st, journal=j),
            )
        return OnlineWeightLearner(min_events=min_events, resolver=resolve)

    async def rebuild(self, tenant_id: str, component: str, builder: Builder) -> Any:
        """Discard cache and snapshot, then replay the full log. Returns the rebuilt component."""
        await self._store.delete_snapshot(tenant_id, component)
        self._handles.pop((tenant_id, component), None)
        return await self._get(tenant_id, component, builder)

    # -- internals ------------------------------------------------------

    def _tenant_key(self, tenant_id: str) -> bytes:
        return hmac.new(self._secret, f"risk-features:{tenant_id}".encode(), hashlib.sha256).digest()

    def _journal(self, tenant_id: str, component: str) -> Callable:
        async def journal(event: dict[str, Any]) -> None:
            await self._store.append_event(tenant_id, component, event)
            LEARNING_EVENTS.labels(tenant_id, component.split("/")[0]).inc()
            handle = self._handles.get((tenant_id, component))
            if handle is not None:
                await self._catch_up(tenant_id, component, handle)
        return journal

    async def _get(self, tenant_id: str, component: str, builder: Builder) -> Any:
        key = (tenant_id, component)
        handle = self._handles.get(key)
        if handle is None:
            async with self._create_lock:
                handle = self._handles.get(key)
                if handle is None:
                    snap = await self._store.load_snapshot(tenant_id, component)
                    seq, state = snap if snap else (0, None)
                    handle = _Handle(builder(state, self._journal(tenant_id, component)), last_seq=seq)
                    self._handles[key] = handle
                    while len(self._handles) > self._max_cached:
                        self._handles.popitem(last=False)
        self._handles.move_to_end(key)
        await self._catch_up(tenant_id, component, handle)
        return handle.component

    async def _catch_up(self, tenant_id: str, component: str, handle: _Handle) -> None:
        async with handle.lock:
            while True:
                batch = await self._store.events_after(tenant_id, component, handle.last_seq)
                if not batch:
                    break
                for seq, event in batch:
                    handle.component.apply(event)
                    handle.last_seq = seq
                    handle.since_snapshot += 1
            if handle.since_snapshot >= self.snapshot_every:
                await self._store.save_snapshot(
                    tenant_id, component, handle.last_seq, handle.component.to_state(),
                )
                handle.since_snapshot = 0
