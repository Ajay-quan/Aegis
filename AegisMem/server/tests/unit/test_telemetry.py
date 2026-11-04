"""Telemetry / metrics tests."""
from __future__ import annotations

from core.observability import metrics


def test_helpers_are_safe_to_call():
    # Should never raise, whether or not prometheus-client is installed.
    metrics.observe_retrieval_results(returned=3, considered=12)
    metrics.observe_retrieval_results(returned=0, considered=0)
    metrics.observe_feedback(recorded=True, outcome="success", reward=0.9)
    metrics.observe_feedback(recorded=False, outcome="", reward=0.0)
    metrics.inc_policy_update()
    metrics.set_replay_gauges(interactions=5, labeled=3, namespaces=2)


def test_render_includes_new_metrics_when_enabled():
    if not metrics.is_enabled():
        return  # exporter disabled (no prometheus-client) — nothing to assert
    metrics.observe_feedback(recorded=True, outcome="success", reward=0.8)
    metrics.inc_policy_update()
    metrics.observe_retrieval_results(returned=2, considered=9)
    metrics.set_replay_gauges(interactions=4, labeled=2, namespaces=1)

    body = metrics.render().decode()
    for name in (
        "aegis_feedback_total",
        "aegis_feedback_reward",
        "aegis_cl_policy_updates_total",
        "aegis_cl_replay_interactions",
        "aegis_cl_replay_labeled_examples",
        "aegis_cl_policy_namespaces",
        "aegis_retrieval_results_returned",
        "aegis_retrieval_candidates_considered",
    ):
        assert name in body, f"missing metric: {name}"
