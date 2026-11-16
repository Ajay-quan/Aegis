# SPDX-License-Identifier: FSL-1.1-ALv2
# Copyright 2026 AegisTrace contributors
"""Tool execution gateway: the policy enforcement point (INV-001, INV-002, INV-004).

Ordering guarantees for every protected call:
  1. Tool must exist in the server-side registry; arguments must validate.
  2. Policy input is built from server-side state (registry metadata, DB grants,
     DB approvals). Model output contributes only the call being judged.
  3. The decision is committed (with the worker's fencing token) before any
     execution. If that commit fails, nothing executes.
  4. Approval consumption, the decision record, and `tool.execution_started`
     commit atomically.
  5. The outcome is recorded afterwards. If the worker dies in between, the
     started-without-outcome record drives reconciliation instead of retry.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Literal

from pydantic import ValidationError
from sqlalchemy import Connection, Engine, text

from aegistrace.approvals import service as approvals
from aegistrace.authorization import rules
from aegistrace.authorization.policy import Decision, PolicyEngine
from aegistrace.authorization.rules import OrgRules
from aegistrace.evidence.canonical import CanonicalizationError
from aegistrace.evidence.events import payload_digest
from aegistrace.observability import GATEWAY_OVERHEAD, POLICY_LATENCY, TOOL_DECISIONS, TOOL_EXECUTIONS
from aegistrace.orchestration.leases import Lease
from aegistrace.orchestration.service import Actor, new_id, record_event
from aegistrace.persistence.db import tenant_tx

from .registry import Classification, ToolContext, ToolRegistry, ToolSpec

MAX_OUTPUT_BYTES = 64 * 1024

Status = Literal["succeeded", "failed", "denied", "pending_approval"]


@dataclass(frozen=True)
class ToolOutcome:
    status: Status
    reason: str
    output: dict[str, Any] | None = None
    approval_id: str | None = None


def _safe_digest(value: Any) -> str:
    try:
        return payload_digest(value)
    except CanonicalizationError:
        return "unrepresentable"


class ToolGateway:
    def __init__(self, engine: Engine, registry: ToolRegistry, policy: PolicyEngine) -> None:
        self._engine = engine
        self._registry = registry
        self._policy = policy

    def _deny(self, tenant_id: str, lease: Lease, actor: Actor, payload: dict[str, Any]) -> ToolOutcome:
        with tenant_tx(self._engine, tenant_id) as conn:
            record_event(conn, lease.run_id, "tool.denied", actor, payload, fencing_token=lease.fencing_token)
        return ToolOutcome("denied", payload["reason"])

    def _prior_outcome(self, conn: Connection, run_id: str, call_key: str) -> ToolOutcome | None:
        row = conn.execute(
            text(
                "SELECT event_type, record->'payload' FROM events WHERE run_id = :r "
                "AND event_type IN ('tool.execution_succeeded', 'tool.execution_failed') "
                "AND record->'payload'->>'call_key' = :k ORDER BY sequence_number DESC LIMIT 1"
            ),
            {"r": run_id, "k": call_key},
        ).one_or_none()
        if row is None:
            return None
        if row[0] == "tool.execution_succeeded":
            return ToolOutcome("succeeded", "recorded", row[1].get("output"))
        return ToolOutcome("failed", row[1].get("error", "recorded_failure"))

    @staticmethod
    def _grants(conn: Connection, tenant_id: str, agent_id: str, tool: str) -> list[dict[str, Any]]:
        return [
            {"tenant_id": tenant_id, "agent_id": a, "tool": t, "max_risk_class": m, "allowed_hosts": list(h)}
            for a, t, m, h in conn.execute(
                text(
                    "SELECT agent_id, tool, max_risk_class, allowed_hosts FROM tool_grants "
                    "WHERE agent_id = :a AND tool = :t"
                ),
                {"a": agent_id, "t": tool},
            )
        ]

    @staticmethod
    def _policy_input(
        tenant_id: str,
        agent_id: str,
        spec: ToolSpec,
        resource: dict[str, Any],
        classification: Classification,
        grants: list[dict[str, Any]],
        approved: bool,
        org_rules: OrgRules,
    ) -> dict[str, Any]:
        return {
            "settings": org_rules.model_dump(exclude={"approval_ttl_minutes"}),
            "principal": {"tenant_id": tenant_id, "agent_id": agent_id},
            "tool": {"name": spec.name, "risk_class": int(spec.risk_class), "network": spec.network},
            "resource": resource,
            "data_classification": classification.name,
            "grants": grants,
            "approval": {"valid": approved},
        }

    def simulate(self, *, tenant_id: str, agent_id: str, tool_name: str, raw_args: Any) -> dict[str, Any]:
        """Policy dry run: same validation and policy input as invoke(), but
        nothing is recorded and nothing executes. Assumes no prior approval."""
        spec = self._registry.get(tool_name)
        if spec is None:
            return {"result": "deny", "reason": "unknown_tool", "policy_revision": None}
        try:
            args = spec.args_model.model_validate(raw_args)
        except ValidationError:
            return {"result": "deny", "reason": "invalid_arguments", "policy_revision": None}
        resource = {"tenant_id": tenant_id, **(spec.resource_of(args) if spec.resource_of else {})}
        classification = spec.classification_of(args) if spec.classification_of else Classification.INTERNAL
        with tenant_tx(self._engine, tenant_id) as conn:
            grants = self._grants(conn, tenant_id, agent_id, spec.name)
            org_rules, _ = rules.load(conn)
        d = self._policy.evaluate(
            self._policy_input(tenant_id, agent_id, spec, resource, classification, grants, False, org_rules)
        )
        return {
            "result": d.result,
            "reason": d.reason,
            "policy_revision": d.policy_revision,
            "risk_class": int(spec.risk_class),
            "input_digest": d.input_digest,
        }

    def invoke(
        self, *, tenant_id: str, agent_id: str, lease: Lease, step: int, tool_name: str, raw_args: Any
    ) -> ToolOutcome:
        started = time.perf_counter()
        actor = Actor(f"gateway:{agent_id}", "service")
        base = {"step": step, "tool": tool_name, "arguments_digest": _safe_digest(raw_args)}

        spec = self._registry.get(tool_name)
        if spec is None:
            return self._deny(tenant_id, lease, actor, {**base, "reason": "unknown_tool"})
        try:
            args = spec.args_model.model_validate(raw_args)
        except ValidationError as exc:
            return self._deny(
                tenant_id, lease, actor, {**base, "reason": "invalid_arguments", "errors": exc.error_count()}
            )

        args_json = args.model_dump(mode="json")
        resource = {"tenant_id": tenant_id, **(spec.resource_of(args) if spec.resource_of else {})}
        classification = spec.classification_of(args) if spec.classification_of else Classification.INTERNAL
        action = {
            "tenant_id": tenant_id,
            "run_id": lease.run_id,
            "agent_id": agent_id,
            "tool": spec.name,
            "arguments": args_json,
            "resource": resource,
        }
        action_digest = payload_digest(action)
        call_key = payload_digest({"action_digest": action_digest, "step": step})
        base = {**base, "action_digest": action_digest, "call_key": call_key, "risk_class": int(spec.risk_class)}

        with tenant_tx(self._engine, tenant_id) as conn:
            prior = self._prior_outcome(conn, lease.run_id, call_key)
            if prior:
                return prior  # resumed run: never repeat a completed call
            grants = self._grants(conn, tenant_id, agent_id, spec.name)
            org_rules, _ = rules.load(conn)
            live = approvals.find_live(conn, lease.run_id, action_digest)

        policy_input = self._policy_input(
            tenant_id, agent_id, spec, resource, classification, grants, bool(live and live[1] == "approved"), org_rules
        )
        t0 = time.perf_counter()
        decision = self._policy.evaluate(policy_input)
        POLICY_LATENCY.observe(time.perf_counter() - t0)
        TOOL_DECISIONS.labels(decision.result, decision.reason).inc()

        with tenant_tx(self._engine, tenant_id) as conn:
            self._persist_decision(conn, lease, agent_id, spec.name, action_digest, resource, decision)
            auth = {
                **base,
                "decision_id": decision.decision_id,
                "decision": decision.result,
                "reason": decision.reason,
                "policy_revision": decision.policy_revision,
            }
            record_event(conn, lease.run_id, "tool.authorization", actor, auth, fencing_token=lease.fencing_token)
            if decision.result == "deny":
                return ToolOutcome("denied", decision.reason)
            if decision.result == "require_approval":
                if approvals.was_rejected(conn, lease.run_id, action_digest):
                    return ToolOutcome("denied", "approval_rejected")
                requested_id = approvals.request(
                    conn,
                    tenant_id,
                    approvals.ApprovalRequest(
                        run_id=lease.run_id,
                        agent_id=agent_id,
                        tool=spec.name,
                        action_digest=action_digest,
                        arguments_digest=payload_digest(args_json),
                        resource=json.dumps(resource, sort_keys=True),
                        risk_class=int(spec.risk_class),
                        policy_revision=decision.policy_revision,
                        summary={"tool": spec.name, "arguments": args_json, "classification": classification.name},
                    ),
                    ttl=timedelta(minutes=org_rules.approval_ttl_minutes),
                )
                record_event(
                    conn,
                    lease.run_id,
                    "approval.requested",
                    actor,
                    {**base, "approval_id": requested_id},
                    fencing_token=lease.fencing_token,
                )
                return ToolOutcome("pending_approval", "approval_required", approval_id=requested_id)
            approval_id: str | None = None
            if decision.reason == "approved":
                approval_id = approvals.consume(conn, lease.run_id, action_digest, decision.policy_revision)
                if approval_id is None:
                    record_event(
                        conn,
                        lease.run_id,
                        "tool.denied",
                        actor,
                        {**base, "reason": "approval_invalid"},
                        fencing_token=lease.fencing_token,
                    )
                    return ToolOutcome("denied", "approval_invalid")
            execution_id = new_id("exe")
            record_event(
                conn,
                lease.run_id,
                "tool.execution_started",
                actor,
                {
                    **base,
                    "execution_id": execution_id,
                    "retry_safe": spec.retry_safe,
                    "approval_id": approval_id,
                    "decision_id": decision.decision_id,
                },
                fencing_token=lease.fencing_token,
            )

        GATEWAY_OVERHEAD.observe(time.perf_counter() - started)
        ctx = ToolContext(tenant_id, lease.run_id, idempotency_key=call_key.removeprefix("sha256:"))
        try:
            out = spec.execute(ctx, args)
            if not isinstance(out, spec.output_model):
                raise TypeError("tool returned unexpected output type")
            output = out.model_dump(mode="json")
            if len(json.dumps(output)) > MAX_OUTPUT_BYTES:
                raise ValueError("tool output too large")
            result = {
                **base,
                "execution_id": execution_id,
                "output": output,
                "output_classification": spec.output_classification.name,
            }
            event_type, outcome = "tool.execution_succeeded", ToolOutcome("succeeded", "executed", output)
        except Exception as exc:  # noqa: BLE001 - every tool failure is recorded, message withheld
            result = {**base, "execution_id": execution_id, "error": type(exc).__name__}
            event_type, outcome = "tool.execution_failed", ToolOutcome("failed", type(exc).__name__)

        with tenant_tx(self._engine, tenant_id) as conn:
            record_event(conn, lease.run_id, event_type, actor, result, fencing_token=lease.fencing_token)
        TOOL_EXECUTIONS.labels(spec.name, outcome.status).inc()
        return outcome

    @staticmethod
    def _persist_decision(
        conn: Connection,
        lease: Lease,
        agent_id: str,
        tool: str,
        action_digest: str,
        resource: dict[str, Any],
        d: Decision,
    ) -> None:
        conn.execute(
            text(
                "INSERT INTO policy_decisions (decision_id, tenant_id, run_id, principal, tool, action_digest, "
                "resource, policy_revision, decision, reason, input_digest) VALUES (:id, "
                "current_setting('app.tenant_id'), :r, :p, :tool, :ad, :res, :rev, :d, :reason, :in)"
            ),
            {
                "id": d.decision_id,
                "r": lease.run_id,
                "p": agent_id,
                "tool": tool,
                "ad": action_digest,
                "res": json.dumps(resource, sort_keys=True),
                "rev": d.policy_revision,
                "d": d.result,
                "reason": d.reason,
                "in": d.input_digest,
            },
        )
