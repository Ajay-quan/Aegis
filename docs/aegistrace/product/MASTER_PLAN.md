# Master plan and requirements traceability

The source directive is the Principal Engineering Directive v2.0. The text received was truncated after §76; the sections after that have not been seen.

## Use cases → evidence

| UC | Status | Primary evidence |
|---|---|---|
| UC-01 Governed research agent | Done | `test_demo1_trusted_execution_with_verified_receipt` |
| UC-02 Unauthorized action prevention | Done | `test_demo2_unauthorized_action_blocked_and_recorded` |
| UC-03 Human-approved export | Done | `test_demo5_human_approval_exact_binding`, Playwright approval test |
| UC-04 Cryptographic investigation | Done | `scripts/demo_tampering.py`, `tests/security/test_tamper_detection.py` |
| UC-05 Failure recovery | Done | `test_uc05_*`, `test_stale_worker_cannot_finalize`, `test_retry_then_new_worker_succeeds` |
| UC-06 Historical replay | Done | `tests/security/test_replay_safety.py`, `test_replay_endpoint` |
| UC-07 Multi-tenant isolation | Done | `test_rls_*`, `test_cross_tenant_access_is_404`, `test_demo7_*` |
| UC-08 Malicious tool server | Done (stdio MCP) | `tests/e2e/test_mcp_security.py` |
| UC-09 Forensics timeline | Done | Dashboard run page, `/v1/runs/{id}/events`, Playwright test |
| UC-10 Developer integration | Done | `examples/quickstart/run.sh`, both SDKs, CLI |

## Flagship demonstrations

| Demo | How to run |
|---|---|
| 1 Trusted execution | `./examples/quickstart/run.sh` |
| 2 Blocked malicious action | Same quickstart (the `email.send` denial) |
| 3 Receipt tampering | `uv run python scripts/demo_tampering.py` |
| 4 Crash recovery | `uv run pytest -k "uc05 or stale_worker or retry_then"` |
| 5 Human approval | Dashboard Approvals page, or `aegistrace approvals approve` |
| 6 Deterministic replay | `aegistrace runs replay <run>` |
| 7 Multi-tenant isolation | `uv run pytest -k "rls or cross_tenant or demo7"` |
| 8 Agent security incident | `uv run pytest tests/e2e/test_mcp_security.py -k end_to_end`, `-k demo8` |

## Release gates (§61–66)

| Gate | Status |
|---|---|
| A Functional | Met locally |
| B Security | Met locally, **except** the independent review |
| C Cryptography | Met |
| D Reliability | Met locally, including backup restoration |
| E Developer experience | Met locally (fresh-install path documented). CI not run. |
| F Evidence | Met for local evidence. Release notes are not written. |

**Overall: release gates are not satisfied for public deployment.** See OPEN_ISSUES items 1–5.
