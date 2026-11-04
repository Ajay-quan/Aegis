# SPDX-License-Identifier: FSL-1.1-ALv2
# Copyright 2026 AegisTrace contributors
"""OPA client. Any failure (timeout, transport, non-200, malformed or
conflicting result) is a deny: policy outages fail closed (INV-012)."""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from typing import Any, Protocol

import httpx

from aegistrace.evidence.events import payload_digest

VALID_RESULTS = {"allow", "deny", "require_approval"}


@dataclass(frozen=True)
class Decision:
    decision_id: str
    result: str
    reason: str
    policy_revision: str
    input_digest: str


class PolicyEngine(Protocol):
    def evaluate(self, policy_input: dict[str, Any]) -> Decision: ...


class OpaPolicyEngine:
    def __init__(self, base_url: str, timeout: float = 0.5, client: httpx.Client | None = None) -> None:
        self._url = base_url.rstrip("/")
        self._client = client or httpx.Client(timeout=timeout)

    def _deny(self, input_digest: str, reason: str) -> Decision:
        return Decision("dec_" + secrets.token_hex(12), "deny", reason, "unavailable", input_digest)

    def evaluate(self, policy_input: dict[str, Any]) -> Decision:
        digest = payload_digest(policy_input)
        try:
            resp = self._client.post(f"{self._url}/v1/data/aegistrace/tools", json={"input": policy_input})
            if resp.status_code != 200:
                return self._deny(digest, "policy_engine_error")
            result = resp.json().get("result") or {}
            decision = result.get("decision") or {}
            revision = result.get("revision")
        except (httpx.HTTPError, ValueError):
            return self._deny(digest, "policy_engine_unavailable")
        if decision.get("result") not in VALID_RESULTS or not isinstance(revision, str):
            return self._deny(digest, "policy_result_malformed")
        return Decision(
            "dec_" + secrets.token_hex(12), decision["result"], str(decision.get("reason", "")), revision, digest
        )
