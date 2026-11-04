"""Outcome-calibrated trust: the memory system learns which sources to believe.

Static trust tables ("tool output = 0.5") are wrong for most real sources. A CRM sync is
nearly always right, while a web-search tool hitting forum posts often is not. We learn this
from outcomes the product already produces:

    quarantine_released   a reviewer approved held content        strong positive
    quarantine_rejected   a reviewer rejected held content        strong negative
    corrected             the user/agent corrected a memory       negative
    confirmed             the user explicitly confirmed a memory  positive
    used                  a retrieved memory was used by the agent weak positive

Each source (``user_message``, ``tool_output``...) and each origin within it (``tool:web_search``,
``domain:reddit.com``) has a Beta posterior. Origins shrink toward their source, so a brand-new
origin starts at the source's learned trust, not a hard-coded constant.

Trust is learned **per tenant, across that tenant's users**: one rejection of a poisoned domain
protects every user. The guard applies learned trust *retroactively*, so memories already stored
from a newly distrusted origin stop being served immediately.

Persistence: the calibrator is a deterministic state machine. ``record`` turns an outcome into an
event; with a journal attached the event is durably appended first and then applied through
replay (see ``services/learning_runtime.py``), so every replica converges on identical state.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

from domain.integrity.provenance import DEFAULT_TRUST, SOURCE_TRUST

COMPONENT = "trust"

# (alpha increment, beta increment) per outcome.
EVENT_WEIGHTS: dict[str, tuple[float, float]] = {
    "quarantine_released": (2.0, 0.0),
    "quarantine_rejected": (0.0, 4.0),
    "corrected": (0.0, 2.0),
    "confirmed": (1.0, 0.0),
    "used": (0.25, 0.0),
}

SOURCE_SPILLOVER = 0.1
INHERIT_FLOOR = 0.8

Journal = Callable[[dict[str, Any]], Awaitable[None]]


@dataclass
class BetaStat:
    alpha: float
    beta: float
    events: int = 0
    updated_at: str | None = None

    @property
    def mean(self) -> float:
        return self.alpha / (self.alpha + self.beta)


def _key(source: str, origin: str = "") -> str:
    return f"{source}|{origin}" if origin else source


class TrustCalibrator:
    def __init__(self, prior_strength: float = 10.0, journal: Journal | None = None) -> None:
        self.k = prior_strength
        self._stats: dict[str, BetaStat] = {}
        self._journal = journal

    # -- state machine --------------------------------------------------

    def _source_stat(self, source: str) -> BetaStat:
        stat = self._stats.get(_key(source))
        if stat is None:
            p = SOURCE_TRUST.get(source, DEFAULT_TRUST)
            stat = BetaStat(alpha=p * self.k, beta=(1 - p) * self.k)
        return stat

    def _origin_stat(self, source: str, origin: str) -> BetaStat:
        stat = self._stats.get(_key(source, origin))
        if stat is None:
            # A new origin inherits the channel's learned trust, floored at a fraction of the
            # static prior: a channel cannot be condemned purely by its bad origins.
            static = SOURCE_TRUST.get(source, DEFAULT_TRUST)
            p = max(self._source_stat(source).mean, INHERIT_FLOOR * static)
            stat = BetaStat(alpha=p * self.k, beta=(1 - p) * self.k)
        return stat

    def apply(self, event: dict[str, Any]) -> None:
        source, origin = event["source"], event.get("origin", "")
        da, db = EVENT_WEIGHTS[event["event"]]
        weight, at = float(event.get("weight", 1.0)), event.get("at")

        # A source is a channel; origins are the actors. When an origin is known, the
        # source moves at a small fraction of the rate, otherwise a handful of bad domains
        # would lower trust (and the risk threshold) for every new origin on that channel.
        # Measured by aegis-bench `learning`: 0.5 doubled held-out FPR, 0.1 does not.
        src_w = weight * (SOURCE_SPILLOVER if origin else 1.0)
        src = self._source_stat(source)
        src.alpha += da * src_w
        src.beta += db * src_w
        src.events += 1
        src.updated_at = at
        self._stats[_key(source)] = src

        if origin:
            org = self._origin_stat(source, origin)
            org.alpha += da * weight
            org.beta += db * weight
            org.events += 1
            org.updated_at = at
            self._stats[_key(source, origin)] = org

    def to_state(self) -> dict[str, Any]:
        return {"k": self.k, "stats": {k: vars(v) for k, v in self._stats.items()}}

    @classmethod
    def from_state(cls, state: dict[str, Any] | None, journal: Journal | None = None) -> "TrustCalibrator":
        cal = cls(prior_strength=(state or {}).get("k", 10.0), journal=journal)
        for k, v in ((state or {}).get("stats") or {}).items():
            cal._stats[k] = BetaStat(**v)
        return cal

    # -- public API -----------------------------------------------------

    async def trust(self, source: str, origin: str = "") -> float:
        return (self._origin_stat(source, origin) if origin else self._source_stat(source)).mean

    async def record(self, source: str, origin: str, event: str, weight: float = 1.0) -> float:
        """Record an outcome. Returns the updated trust for (source, origin)."""
        if event not in EVENT_WEIGHTS:
            raise ValueError(f"unknown trust event: {event}")
        ev = {
            "source": source, "origin": origin or "", "event": event, "weight": weight,
            "at": datetime.now(timezone.utc).isoformat(),
        }
        if self._journal is not None:
            await self._journal(ev)  # append durably, then applied via replay
        else:
            self.apply(ev)
        return await self.trust(source, origin)

    async def snapshot(self) -> list[dict[str, Any]]:
        rows = []
        for key, s in self._stats.items():
            source, _, origin = key.partition("|")
            rows.append({
                "source": source,
                "origin": origin,
                "trust": round(s.mean, 4),
                "default_trust": SOURCE_TRUST.get(source, DEFAULT_TRUST),
                "events": s.events,
                "updated_at": s.updated_at,
            })
        rows.sort(key=lambda r: r["trust"])
        return rows


def memory_source_origin(metadata: dict[str, Any], fallback_source: Any = "") -> tuple[str, str]:
    prov = metadata.get("provenance") or {}
    source = prov.get("source") or (fallback_source.value if hasattr(fallback_source, "value") else str(fallback_source))
    return source, prov.get("origin", "")
