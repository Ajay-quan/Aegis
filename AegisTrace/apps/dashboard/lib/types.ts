// SPDX-License-Identifier: FSL-1.1-ALv2
// Copyright 2026 AegisTrace contributors
export interface Run {
  id: string; agent_id: string; project_id: string; state: string; attempt: number; last_sequence: number;
  head_hash: string; result: unknown; created_at: string; updated_at: string;
}
export interface Stats {
  runs_by_state: Record<string, number>; pending_approvals: number; policy_denials_24h: number;
  run_duration_ms_24h: { p50: number | null; p95: number | null };
}
export interface Decision {
  decision_id: string; run_id: string; principal: string; tool: string; resource: string | null;
  policy_revision: string; decision: string; reason: string; input_digest: string; created_at: string;
}
export interface Approval {
  id: string; run_id: string; agent_id: string; tool: string; risk_class: number; resource: string | null;
  summary: Record<string, unknown>; status: string; expires_at: string; requested_at: string; decided_by: string | null;
}
export interface Agent { id: string; project_id: string; name: string; model_provider: string; model_id: string }
export interface EventRec {
  event_id: string; sequence_number: number; event_type: string; actor_id: string; timestamp: string;
  payload_digest: string; previous_event_hash: string; current_event_hash: string; payload?: Record<string, unknown>;
}
export const RISK = ["Pure", "Controlled read", "Reversible write", "Consequential write", "Irreversible"];
