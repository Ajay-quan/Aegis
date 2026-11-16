// SPDX-License-Identifier: FSL-1.1-ALv2
// Copyright 2026 AegisTrace contributors
// Content for the public pages. Statuses describe what runs in the code today:
// Built = works and is tested; In progress = partly built; Planned = not built yet.

export type Status = "Built" | "In progress" | "Planned";

export const PILLARS: { name: string; line: string; body: string; points: [string, Status][] }[] = [
  {
    name: "Mem",
    line: "Memory that lasts, and stays correct.",
    body: "Persistent memory for agents, found by meaning and by keyword. Contradictions are caught, and every fact can be traced, corrected and erased.",
    points: [["Hybrid semantic and keyword retrieval", "Built"], ["Contradiction detection and review", "Built"], ["Knowledge-graph relationships", "In progress"]],
  },
  {
    name: "Trace",
    line: "Every step an agent takes, on the record.",
    body: "One trace per run, across every model and tool call. Each step is signed, so the record can be verified offline.",
    points: [["End-to-end traces across services", "Built"], ["Signed, verifiable execution records", "Built"], ["Token usage and estimated cost", "Built"]],
  },
  {
    name: "Runtime",
    line: "Runs that finish, even when things fail.",
    body: "Agents run on a durable state machine. When a worker crashes or a dependency restarts, another worker picks the run up.",
    points: [["Durable orchestration with leases", "Built"], ["Recovery from crashes and outages", "Built"], ["Multi-agent workflow definitions", "Planned"]],
  },
  {
    name: "Guard",
    line: "Nothing runs until you allow it.",
    body: "Default-deny permissions enforced outside the model. Risky actions wait for a person, and each organization is sealed off from every other.",
    points: [["Policy enforcement and human approval", "Built"], ["Roles, API keys and an audit log", "Built"], ["Encryption at rest and erasure", "Built"]],
  },
  {
    name: "Eval",
    line: "Know an agent is better before it ships.",
    body: "Test suites, benchmarks and regression checks that show whether a change helped, and where it failed.",
    points: [["Memory retrieval benchmarks", "Built"], ["Agent test suites and regression checks", "Planned"], ["Side-by-side model comparisons", "Planned"]],
  },
  {
    name: "Optimize",
    line: "The same answer, for fewer tokens.",
    body: "Compress context, cache what repeats and route each task to the smallest model that does it well.",
    points: [["Token and cost reporting", "Built"], ["Context compression and caching", "Planned"], ["Cost reduction experiments", "Planned"]],
  },
  {
    name: "Models",
    line: "Any model, hosted or local.",
    body: "Register hosted APIs and local models in one hub, test the connection, and run agents on them. Keys are stored encrypted.",
    points: [["Hosted and local models (OpenAI-compatible, Ollama)", "Built"], ["Connection tests and encrypted keys", "Built"], ["Fine-tuning with LoRA and QLoRA", "Planned"]],
  },
  {
    name: "Studio",
    line: "One place to build, watch and govern.",
    body: "The workspace where developers build agents, inspect runs, review approvals, explore memory and manage the platform.",
    points: [["Agents, runs, approvals, memory and security", "Built"], ["Sign-in, members, roles and API keys", "Built"], ["Evaluation and optimization views", "Planned"]],
  },
];

export const STUDIO: { group: string; items: [string, string, Status][] }[] = [
  { group: "Workspace", items: [
    ["Overview", "Health, run volume, tokens, cost and what needs you.", "Built"],
    ["Agent Builder", "Create agents, choose a model, write instructions, keep versions.", "Built"],
    ["Memory Explorer", "Search, review, correct and erase what agents remember.", "Built"],
    ["Trace Viewer", "Every step of a run, with timings and verifiable evidence.", "Built"],
    ["Model Hub", "Register hosted and local models and test the connection.", "Built"],
  ] },
  { group: "Operations", items: [
    ["Security Center", "Permissions, rules, approvals, erasures and the audit trail.", "Built"],
    ["Settings", "Members, roles, API keys, usage and the audit log.", "Built"],
    ["Optimization Center", "Token use and cost today; savings experiments next.", "In progress"],
    ["Deployment Center", "Service health today; environments next.", "In progress"],
    ["Evaluation Lab", "Test suites, comparisons, failure cases and regressions.", "Planned"],
  ] },
];

export const CAPABILITIES: [string, string, Status][] = [
  ["Verifiable execution", "Signed receipts for every run. Any change to the record is detected.", "Built"],
  ["MCP security gateway", "Every tool reached through MCP is checked, authorized and recorded.", "Built"],
  ["Execution replay", "Rebuild a past run to debug it, without repeating a side effect.", "Built"],
  ["Multi-tenancy", "Organizations, agents, memories, keys and records sealed from one another.", "Built"],
];

export const ROADMAP: { when: string; title: string; products: string[]; body: string; state: string }[] = [
  { when: "Now", title: "Memory and evidence", products: ["Mem", "Trace"], body: "Reliable memory, signed execution records, trace inspection and developer APIs.", state: "Largely built" },
  { when: "Next", title: "One workspace, governed", products: ["Studio", "Guard", "Models"], body: "The components in one workspace, with roles, keys, audit and a model hub.", state: "In progress" },
  { when: "Later", title: "The full harness", products: ["Runtime", "Eval", "Optimize"], body: "Workflows, evaluation and efficiency, each usable on its own.", state: "Planned" },
];

export const INTEGRATIONS: { group: string; items: [string, boolean][] }[] = [
  { group: "Models", items: [["OpenAI-compatible APIs", true], ["Ollama", true], ["Anthropic (memory server)", true], ["Google Gemini", false], ["vLLM, llama.cpp (verified)", false]] },
  { group: "Agents and tools", items: [["MCP, local and remote", true], ["LangGraph", true], ["LangChain", true], ["LoRA, QLoRA, TRL", false]] },
  { group: "Data", items: [["PostgreSQL", true], ["Qdrant", true], ["Neo4j", true], ["Redis", true]] },
  { group: "Platform", items: [["OpenTelemetry", true], ["Single sign-on (OIDC)", true], ["Python and TypeScript SDKs", true], ["Docker", true], ["AWS", false]] },
];
