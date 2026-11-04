# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 AegisTrace contributors
package aegistrace.tools_test

import rego.v1

import data.aegistrace.tools

base := {
	"principal": {"tenant_id": "tnt_a", "agent_id": "agt_1"},
	"resource": {"tenant_id": "tnt_a"},
	"tool": {"name": "docs.read", "risk_class": 1, "network": false},
	"grants": [{"tenant_id": "tnt_a", "agent_id": "agt_1", "tool": "docs.read", "max_risk_class": 1}],
	"approval": {"valid": false},
}

test_allow_granted if tools.decision.result == "allow" with input as base

test_default_deny_no_grant if {
	tools.decision.result == "deny" with input as object.union(base, {"grants": []})
}

test_deny_other_agents_grant if {
	g := [{"tenant_id": "tnt_a", "agent_id": "agt_2", "tool": "docs.read", "max_risk_class": 1}]
	tools.decision.result == "deny" with input as object.union(base, {"grants": g})
}

test_deny_cross_tenant_resource if {
	d := tools.decision with input as object.union(base, {"resource": {"tenant_id": "tnt_b"}})
	d.reason == "cross_tenant_resource"
}

test_deny_class_above_grant if {
	t := {"name": "docs.read", "risk_class": 2, "network": false}
	tools.decision.reason == "risk_class_exceeds_grant" with input as object.union(base, {"tool": t})
}

high := object.union(base, {
	"tool": {"name": "data.export", "risk_class": 3, "network": false},
	"grants": [{"tenant_id": "tnt_a", "agent_id": "agt_1", "tool": "data.export", "max_risk_class": 3}],
})

test_class3_requires_approval if tools.decision.result == "require_approval" with input as high

test_class3_allowed_with_approval if {
	tools.decision.result == "allow" with input as object.union(high, {"approval": {"valid": true}})
}

net := object.union(base, {
	"tool": {"name": "http.fetch", "risk_class": 1, "network": true},
	"grants": [{
		"tenant_id": "tnt_a", "agent_id": "agt_1", "tool": "http.fetch", "max_risk_class": 1,
		"allowed_hosts": ["docs.example.com"],
	}],
})

test_network_allowlisted if {
	tools.decision.result == "allow" with input as object.union(net, {"resource": {"tenant_id": "tnt_a", "host": "docs.example.com"}})
}

test_network_not_allowlisted if {
	d := tools.decision with input as object.union(net, {"resource": {"tenant_id": "tnt_a", "host": "169.254.169.254"}})
	d.reason == "destination_not_allowed"
}

test_restricted_data_needs_approval if {
	tools.decision.result == "require_approval" with input as object.union(base, {"data_classification": "RESTRICTED"})
}

# -- per-organization settings --------------------------------------------------

test_org_block_overrides_grant if {
	d := tools.decision with input as object.union(base, {"settings": {"blocked_tools": ["docs.read"]}})
	d.reason == "tool_blocked_by_org_policy"
}

test_org_block_overrides_valid_approval if {
	i := object.union(high, {"approval": {"valid": true}, "settings": {"blocked_tools": ["data.export"]}})
	tools.decision.result == "deny" with input as i
}

test_strict_org_lowers_approval_threshold if {
	tools.decision.result == "require_approval" with input as object.union(base, {"settings": {"approval_min_risk_class": 1}})
}

test_permissive_org_raises_threshold if {
	tools.decision.result == "allow" with input as object.union(high, {"settings": {"approval_min_risk_class": 4}})
}

test_always_require_approval_list if {
	tools.decision.result == "require_approval" with input as object.union(base, {"settings": {"always_require_approval": ["docs.read"]}})
}

test_restricted_toggle_off if {
	i := object.union(base, {"data_classification": "RESTRICTED", "settings": {"restricted_data_requires_approval": false}})
	tools.decision.result == "allow" with input as i
}

test_defaults_without_settings if {
	tools.decision.result == "require_approval" with input as high
}
