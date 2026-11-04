# SPDX-License-Identifier: FSL-1.1-ALv2
# Copyright 2026 AegisTrace contributors
"""Replay modes:

A  cryptographic verification   -> aegistrace.evidence.verifier (not here)
B  state reconstruction         -> reconstruct()
C  deterministic decision replay -> replay_decisions()
D  controlled execution fork    -> a *new* run, created by the API with
                                   explicit authorization (not here)
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from aegistrace.agents.model import ModelAdapter, ModelError, ModelResponse

SUPPORTED_SCHEMA_VERSIONS = {1}


class ReplayStatus(StrEnum):
    IDENTICAL = "IDENTICAL"
    DIVERGED = "DIVERGED"
    MISSING_DEPENDENCY = "MISSING_DEPENDENCY"
    INCOMPATIBLE_VERSION = "INCOMPATIBLE_VERSION"
    INCOMPLETE_HISTORY = "INCOMPLETE_HISTORY"


@dataclass
class RunView:
    state: str | None = None
    attempts: int = 0
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    denials: list[dict[str, Any]] = field(default_factory=list)
    approvals: dict[str, str] = field(default_factory=dict)
    model_steps: int = 0
    result: Any = None
    last_sequence: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "attempts": self.attempts,
            "tool_calls": self.tool_calls,
            "denials": self.denials,
            "approvals": self.approvals,
            "model_steps": self.model_steps,
            "result": self.result,
            "last_sequence": self.last_sequence,
        }


class ReplayError(Exception):
    def __init__(self, status: ReplayStatus, detail: str) -> None:
        super().__init__(detail)
        self.status = status


def _check(records: list[dict[str, Any]]) -> None:
    for i, r in enumerate(records, 1):
        if r.get("schema_version") not in SUPPORTED_SCHEMA_VERSIONS:
            raise ReplayError(ReplayStatus.INCOMPATIBLE_VERSION, f"event {i}: unsupported schema version")
        if r.get("sequence_number") != i:
            raise ReplayError(ReplayStatus.INCOMPLETE_HISTORY, f"expected sequence {i}")


def reconstruct(records: list[dict[str, Any]]) -> RunView:
    """Replay B: fold events into a state projection. Payload-withheld events
    still advance sequence but contribute only what their type implies."""
    _check(records)
    v = RunView()
    for r in records:
        p = r.get("payload") or {}
        t = r["event_type"]
        v.last_sequence = r["sequence_number"]
        if t == "run.created":
            v.state = "CREATED"
        elif t == "run.state_changed":
            v.state = p.get("to", v.state)
            if p.get("to") == "RUNNING":
                v.attempts += 1
            if "result" in p:
                v.result = p["result"]
        elif t == "model.invoked":
            v.model_steps += 1
        elif t == "tool.execution_succeeded":
            v.tool_calls.append({"step": p.get("step"), "tool": p.get("tool"), "status": "succeeded"})
        elif t == "tool.execution_failed":
            v.tool_calls.append({"step": p.get("step"), "tool": p.get("tool"), "status": "failed"})
        elif t == "tool.denied" or (t == "tool.authorization" and p.get("decision") == "deny"):
            v.denials.append({"step": p.get("step"), "tool": p.get("tool"), "reason": p.get("reason")})
        elif t == "approval.requested":
            v.approvals[p.get("approval_id", "?")] = "pending"
        elif t == "approval.decided":
            v.approvals[p.get("approval_id", "?")] = p.get("decision", "?")
    return v


@dataclass
class Divergence:
    step: int
    expected: Any
    actual: Any


@dataclass
class ReplayResult:
    status: ReplayStatus
    steps_compared: int
    divergence: Divergence | None = None
    detail: str = ""
    original: dict[str, Any] | None = None
    reconstructed: dict[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "steps_compared": self.steps_compared,
            "detail": self.detail,
            "divergence": self.divergence.__dict__ if self.divergence else None,
            "original": self.original,
            "reconstructed": self.reconstructed,
        }


class _RecordedModel:
    provider = "recorded"
    model_id = "recorded"

    def __init__(self, responses: dict[int, ModelResponse]) -> None:
        self._r = responses

    def complete(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> ModelResponse:
        step = sum(1 for m in messages if m["role"] == "assistant")
        if step not in self._r:
            raise ModelError("missing_recorded_response")
        return self._r[step]


def replay_decisions(records: list[dict[str, Any]], model: ModelAdapter | None = None) -> ReplayResult:
    """Replay C: drive the agent decision loop with recorded tool outcomes.

    With model=None, recorded model responses are used (checks that the
    history is self-consistent and complete). With a candidate model (e.g. a
    new agent version, or a deterministic mock), its proposals are compared
    to the recorded ones; the first difference is reported as a divergence.
    No tool, network, or database is ever contacted.
    """
    try:
        _check(records)
    except ReplayError as exc:
        return ReplayResult(exc.status, 0, detail=str(exc))
    recorded_resp: dict[int, ModelResponse] = {}
    outcomes: dict[int, dict[str, Any]] = {}
    task = ""
    for r in records:
        p: Any = r.get("payload")
        if (
            r["event_type"] in ("model.invoked", "tool.execution_succeeded", "tool.execution_failed", "tool.denied")
            and p is None
        ):
            return ReplayResult(
                ReplayStatus.MISSING_DEPENDENCY,
                0,
                detail=f"event {r['sequence_number']} payload withheld; cannot replay",
            )
        if r["event_type"] == "model.invoked":
            recorded_resp[p["step"]] = ModelResponse.from_record(p["response"])
        elif r["event_type"] == "tool.execution_succeeded":
            outcomes[p["step"]] = {"untrusted_tool_output": p["output"], "status": "succeeded", "reason": "executed"}
        elif r["event_type"] == "tool.execution_failed":
            outcomes[p["step"]] = {"untrusted_tool_output": None, "status": "failed", "reason": p["error"]}
        elif r["event_type"] == "tool.denied" or (
            r["event_type"] == "tool.authorization" and (p or {}).get("decision") == "deny"
        ):
            outcomes[p["step"]] = {"untrusted_tool_output": None, "status": "denied", "reason": p["reason"]}
        elif r["event_type"] == "run.created" and isinstance(p, dict):
            task = (p.get("input") or {}).get("task", "")

    candidate: ModelAdapter = model or _RecordedModel(recorded_resp)
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": "replay"},
        {"role": "user", "content": json.dumps({"task": task})},
    ]
    step = 0
    for step in range(len(recorded_resp)):  # noqa: B007
        try:
            resp = candidate.complete(messages, [])
        except ModelError as exc:
            return ReplayResult(ReplayStatus.MISSING_DEPENDENCY, step, detail=exc.classification)
        expected = recorded_resp[step].to_record()
        actual = resp.to_record()
        expected.pop("usage", None)
        actual.pop("usage", None)
        if actual != expected:
            return ReplayResult(ReplayStatus.DIVERGED, step, Divergence(step, expected, actual))
        messages.append({"role": "assistant", "content": json.dumps(resp.to_record())})
        if resp.tool_call is None:
            break
        if step not in outcomes:
            # Proposal recorded but no outcome: run paused (approval) or was interrupted.
            if step == len(recorded_resp) - 1:
                step += 1
                break
            return ReplayResult(ReplayStatus.MISSING_DEPENDENCY, step, detail=f"no recorded outcome for step {step}")
        messages.append({"role": "user", "content": json.dumps(outcomes[step])})
    view = reconstruct(records).as_dict()
    return ReplayResult(ReplayStatus.IDENTICAL, len(recorded_resp), original=view, reconstructed=view)
