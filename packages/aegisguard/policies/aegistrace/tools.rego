# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 AegisTrace contributors
# Tool authorization. Default deny. Input is built by the tool gateway from
# server-side state only (registry, grants, approvals); nothing in it comes
# from model output except the proposed tool name, arguments, and resource,
# which are what is being judged.
package aegistrace.tools

import rego.v1

revision := "tools-v2"

default decision := {"result": "deny", "reason": "no_matching_grant"}

grant := g if {
	some g in input.grants
	g.tool == input.tool.name
	g.agent_id == input.principal.agent_id
	g.tenant_id == input.principal.tenant_id
}

tenant_ok if input.principal.tenant_id == input.resource.tenant_id

destination_ok if not input.tool.network

destination_ok if {
	input.tool.network
	input.resource.host in grant.allowed_hosts
}

# Per-organization settings (input.settings), loaded by the gateway from the
# tenant's stored rules. Absent settings fall back to the defaults below.
default approval_min_risk_class := 3

approval_min_risk_class := input.settings.approval_min_risk_class

default restricted_requires_approval := true

restricted_requires_approval := input.settings.restricted_data_requires_approval

blocked if input.tool.name in object.get(input, ["settings", "blocked_tools"], [])

needs_approval if input.tool.risk_class >= approval_min_risk_class

needs_approval if {
	restricted_requires_approval
	input.data_classification == "RESTRICTED"
}

needs_approval if input.tool.name in object.get(input, ["settings", "always_require_approval"], [])

decision := {"result": "deny", "reason": "cross_tenant_resource"} if not tenant_ok

# An organization-wide block overrides any grant or approval.
decision := {"result": "deny", "reason": "tool_blocked_by_org_policy"} if {
	tenant_ok
	blocked
}

decision := {"result": "deny", "reason": "destination_not_allowed"} if {
	tenant_ok
	not blocked
	grant
	not destination_ok
}

decision := {"result": "deny", "reason": "risk_class_exceeds_grant"} if {
	tenant_ok
	not blocked
	destination_ok
	input.tool.risk_class > grant.max_risk_class
}

decision := {"result": "allow", "reason": "granted"} if {
	tenant_ok
	not blocked
	destination_ok
	input.tool.risk_class <= grant.max_risk_class
	not needs_approval
}

decision := {"result": "require_approval", "reason": "approval_required"} if {
	tenant_ok
	not blocked
	destination_ok
	input.tool.risk_class <= grant.max_risk_class
	needs_approval
	not input.approval.valid
}

decision := {"result": "allow", "reason": "approved"} if {
	tenant_ok
	not blocked
	destination_ok
	input.tool.risk_class <= grant.max_risk_class
	needs_approval
	input.approval.valid
}
