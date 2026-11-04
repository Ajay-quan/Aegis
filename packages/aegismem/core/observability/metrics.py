"""Prometheus metrics. Labels are low-cardinality by construction: route *templates*,
decision enums and tenant ids (bounded by customers), never user ids, memory ids or content."""
from __future__ import annotations

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram

REGISTRY = CollectorRegistry(auto_describe=True)

HTTP_REQUESTS = Counter(
    "aegis_http_requests_total", "HTTP requests", ["method", "route", "status"], registry=REGISTRY)
HTTP_LATENCY = Histogram(
    "aegis_http_request_seconds", "HTTP request latency", ["method", "route"], registry=REGISTRY,
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5))
RATE_LIMITED = Counter(
    "aegis_rate_limited_total", "Requests rejected by per-tenant rate limits", ["class"],
    registry=REGISTRY)
AUTH_FAILURES = Counter(
    "aegis_auth_failures_total", "Rejected API calls", ["reason"], registry=REGISTRY)

GUARD_DECISIONS = Counter(
    "aegis_guard_decisions_total", "Read-time guard decisions that changed what was served",
    ["tenant", "action", "reason"], registry=REGISTRY)
WRITES = Counter(
    "aegis_memory_writes_total", "Memory writes by outcome", ["tenant", "source", "outcome"],
    registry=REGISTRY)
ERASURES = Counter(
    "aegis_erasures_total", "Erasure requests", ["tenant", "verified"], registry=REGISTRY)
ERASED_ITEMS = Counter(
    "aegis_erased_items_total", "Items erased by relation", ["tenant", "relation"], registry=REGISTRY)
OUTBOX_PROCESSED = Counter(
    "aegis_outbox_ops_total", "Vector-sync outbox operations processed", ["op", "result"],
    registry=REGISTRY)
LEARNING_EVENTS = Counter(
    "aegis_learning_events_total", "Durable learning events appended", ["tenant", "component"],
    registry=REGISTRY)

# --- Retrieval quality and learning-loop telemetry (ported from the pre-merge main branch) ---
RETRIEVAL_RESULTS = Histogram(
    "aegis_retrieval_results_returned", "Memories returned per retrieval", registry=REGISTRY,
    buckets=(0, 1, 2, 3, 5, 10, 20, 50))
RETRIEVAL_CANDIDATES = Histogram(
    "aegis_retrieval_candidates_considered", "Candidates considered per retrieval", registry=REGISTRY,
    buckets=(0, 5, 10, 25, 50, 100, 250, 500))
RETRIEVAL_EMPTY = Counter(
    "aegis_retrieval_empty_total", "Retrievals that returned nothing", registry=REGISTRY)
FEEDBACK_TOTAL = Counter(
    "aegis_feedback_total", "Feedback submissions", ["outcome"], registry=REGISTRY)
FEEDBACK_REWARD = Histogram(
    "aegis_feedback_reward", "Share of retrieved memories marked used", registry=REGISTRY,
    buckets=(0, 0.1, 0.25, 0.5, 0.75, 0.9, 1.0))
POLICY_UPDATES = Counter(
    "aegis_cl_policy_updates_total", "Ranking-policy updates from feedback", registry=REGISTRY)
REPLAY_INTERACTIONS = Gauge(
    "aegis_cl_replay_interactions", "Interactions held by the experimental replay buffer", registry=REGISTRY)
REPLAY_LABELED = Gauge(
    "aegis_cl_replay_labeled_examples", "Labelled examples in the replay buffer", registry=REGISTRY)
CL_NAMESPACES = Gauge(
    "aegis_cl_policy_namespaces", "Namespaces with an adapted ranking policy", registry=REGISTRY)


def is_enabled() -> bool:
    return True  # prometheus-client is a core dependency


def observe_retrieval_results(returned: int, considered: int) -> None:
    RETRIEVAL_RESULTS.observe(returned)
    RETRIEVAL_CANDIDATES.observe(considered)
    if returned == 0:
        RETRIEVAL_EMPTY.inc()


def observe_feedback(recorded: bool, outcome: str, reward: float) -> None:
    FEEDBACK_TOTAL.labels(outcome or ("recorded" if recorded else "rejected")).inc()
    if recorded:
        FEEDBACK_REWARD.observe(reward)


def inc_policy_update(n: int = 1) -> None:
    POLICY_UPDATES.inc(n)


def set_replay_gauges(interactions: int, labeled: int, namespaces: int) -> None:
    REPLAY_INTERACTIONS.set(interactions)
    REPLAY_LABELED.set(labeled)
    CL_NAMESPACES.set(namespaces)


def render() -> bytes:
    from prometheus_client import generate_latest
    return generate_latest(REGISTRY)
