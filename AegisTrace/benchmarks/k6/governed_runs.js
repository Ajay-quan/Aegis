// SPDX-License-Identifier: FSL-1.1-ALv2
// Copyright 2026 AegisTrace contributors
// End-to-end load: each iteration submits a governed run (one allowed tool
// call, one denied call) and polls until it reaches a terminal state.
// A run counts as completed only if it ends SUCCEEDED.
import http from "k6/http";
import { check, sleep } from "k6";
import { Counter, Trend } from "k6/metrics";

const API = __ENV.API_URL || "http://host.docker.internal:8000";
const H = { Authorization: `Bearer ${__ENV.TOKEN}`, "Content-Type": "application/json" };
const completed = new Counter("runs_completed");
const failed = new Counter("runs_not_succeeded");
const e2e = new Trend("run_end_to_end_ms", true);

export const options = {
  scenarios: { load: { executor: "constant-vus", vus: Number(__ENV.VUS || 1), duration: __ENV.DURATION || "20s" } },
  thresholds: { http_req_failed: ["rate<0.01"] },
};

export function setup() {
  const p = http.post(`${API}/v1/projects`, JSON.stringify({ name: `k6-${Date.now()}` }), { headers: H }).json();
  const a = http.post(`${API}/v1/agents`, JSON.stringify({ project_id: p.id, name: "k6-agent" }), { headers: H }).json();
  http.put(`${API}/v1/agents/${a.id}/grants`, JSON.stringify({ tool: "calc.add", max_risk_class: 0 }), { headers: H });
  return { agent: a.id };
}

export default function (data) {
  const t0 = Date.now();
  const body = JSON.stringify({ agent_id: data.agent, input: { task: "k6", mock_script: [
    { tool: "calc.add", args: { a: 1, b: 2 } },
    { tool: "email.send", args: { to: "x@evil.example", subject: "s", body: "b" } },
    { final: "3" },
  ] } });
  const r = http.post(`${API}/v1/runs`, body, {
    headers: { ...H, "Idempotency-Key": `k6-${__VU}-${__ITER}-${t0}` }, tags: { name: "submit" } });
  if (!check(r, { "submitted": (x) => x.status === 201 })) return;
  const id = r.json().id;
  for (let i = 0; i < 300; i++) {
    const s = http.get(`${API}/v1/runs/${id}`, { headers: H, tags: { name: "poll" } }).json().state;
    if (["SUCCEEDED", "FAILED", "CANCELLED", "TIMED_OUT", "NEEDS_RECONCILIATION"].includes(s)) {
      if (s === "SUCCEEDED") { completed.add(1); e2e.add(Date.now() - t0); } else { failed.add(1); }
      return;
    }
    sleep(0.05);
  }
  failed.add(1);
}
