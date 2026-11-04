"""Write-time provenance, trust and quarantine.

Every memory carries a provenance record in ``metadata["provenance"]``:

    {"source": "user_message", "trust": 0.9, "origin_ref": "...", "derived_from": [...]}

Rules:
  * Trust starts from the source type (what the user said directly is trusted more than a
    scraped document).
  * **Non-amplification:** a derived memory (reflection, summary, merge) can never be
    more trusted than its least-trusted source. This blocks "provenance laundering", where
    consolidation turns an untrusted web snippet into an authoritative-looking fact.
  * Low-trust content that reads like an instruction to the agent is quarantined
    (status=pending) instead of being served. This is the main persistent-poisoning vector.
"""
from __future__ import annotations

import re
from typing import Any

SOURCE_TRUST: dict[str, float] = {
    "user_message": 0.9,
    "system": 0.9,
    "agent_observation": 0.6,
    "tool_output": 0.5,
    "reflection": 0.6,
    "ingestion": 0.3,  # bulk / external documents, web pages
}
DEFAULT_TRUST = 0.5
QUARANTINE_TRUST_CEILING = 0.7

# Phrases that address the agent rather than describe the user or the world.
_INJECTION_PATTERNS = [
    r"\bignore (all |any )?(previous|prior|above) (instructions|rules|messages)\b",
    r"\bdisregard (the |all )?(previous|prior|system)\b",
    r"\byou (must|should) (now )?(always|never)\b",
    r"\b(from now on|going forward),? (you|the assistant|the agent)\b",
    r"\b(system prompt|developer message|jailbreak)\b",
    r"\b(send|forward|email|post|upload) .{0,40}\b(password|api key|token|credentials|secret)s?\b",
    r"\bwhen (asked|the user asks) .{0,60}\b(reply|respond|say|answer)\b",
    r"<\s*/?\s*(system|instructions?)\s*>",
]
_INJECTION_RE = re.compile("|".join(_INJECTION_PATTERNS), re.IGNORECASE)


def _val(v: Any) -> str:
    return v.value if hasattr(v, "value") else str(v)


def base_trust(source_type: Any) -> float:
    return SOURCE_TRUST.get(_val(source_type), DEFAULT_TRUST)


def derived_trust(own: float, source_trusts: list[float]) -> float:
    """Non-amplification: derived trust is capped by the weakest source."""
    return min([own, *source_trusts]) if source_trusts else own


def injection_signals(text: str) -> list[str]:
    return [m.group(0) for m in _INJECTION_RE.finditer(text)]


def should_quarantine(text: str, trust: float) -> str | None:
    """Return a reason if the memory must be held for review, else None."""
    hits = injection_signals(text)
    if hits and trust < QUARANTINE_TRUST_CEILING:
        return f"instruction-like content from low-trust source: {hits[0]!r}"
    return None


def get_provenance(metadata: dict[str, Any]) -> dict[str, Any]:
    return metadata.get("provenance") or {}


def get_trust(metadata: dict[str, Any], default: float = DEFAULT_TRUST) -> float:
    return float(get_provenance(metadata).get("trust", default))


def derived_from(metadata: dict[str, Any]) -> list[str]:
    """All upstream memory ids a memory was derived from."""
    ids = list(get_provenance(metadata).get("derived_from") or [])
    ids += metadata.get("derivation_ids") or []  # reflections (legacy field)
    return list(dict.fromkeys(ids))
