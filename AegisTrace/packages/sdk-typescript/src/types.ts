// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 AegisTrace contributors
export type RunState =
  | "CREATED" | "VALIDATING" | "QUEUED" | "RUNNING" | "WAITING_FOR_APPROVAL" | "RETRY_SCHEDULED"
  | "RECOVERING" | "SUCCEEDED" | "FAILED" | "CANCELLED" | "TIMED_OUT" | "NEEDS_RECONCILIATION";

export interface Agent {
  id: string;
  project_id: string;
  name: string;
  model_provider: string;
  model_id: string;
}

export interface Run {
  id: string;
  agent_id: string;
  project_id: string;
  state: RunState;
  attempt: number;
  last_sequence: number;
  head_hash: string;
  result: unknown;
  created_at: string;
  updated_at: string;
}

export interface ExecutionEvent {
  event_id: string;
  tenant_id: string;
  project_id: string;
  run_id: string;
  sequence_number: number;
  event_type: string;
  schema_version: number;
  actor_id: string;
  causation_id: string | null;
  correlation_id: string;
  timestamp: string;
  payload_digest: string;
  previous_event_hash: string;
  current_event_hash: string;
  protocol: string;
  payload?: unknown;
}

export interface Approval {
  id: string;
  run_id: string;
  agent_id: string;
  tool: string;
  risk_class: number;
  resource: string | null;
  summary: Record<string, unknown>;
  status: "pending" | "approved" | "rejected" | "consumed" | "expired";
  expires_at: string;
  requested_at: string;
  decided_by: string | null;
}

export interface Page<T> {
  items: T[];
  next_cursor?: string | null;
}

export interface ReplayReport {
  reconstructed_state: Record<string, unknown> & { state: RunState | null };
  projection_state: RunState;
  state_matches_projection: boolean;
  decision_replay: { status: string; steps_compared: number; [k: string]: unknown };
}
