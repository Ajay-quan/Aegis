# Incident response

Each procedure covers containment, investigation, recovery, and post-incident verification. Every procedure ends with: `scripts/ops/verify_restored.py` against the live DB (owner URL), the trust store and the anchor, and **zero failures**.

## Worker compromise
- **Contain:**
  1. Scale workers to 0.
  2. Rotate the DB app password and the signing key.
  3. Mark the old signing key `revoked_at=<detection time>`, or `compromised` if exfiltration is possible.
- **Investigate:**
  - Policy decisions and `tool.execution_*` events in the window.
  - Runs whose checkpoints were signed by the old key after the suspected start.
- **Recover:** redeploy from a clean image digest, then re-verify all runs.

## Suspected receipt tampering
1. Re-export the bundle from the DB and verify it with the **anchor**.
2. Compare the reported `trusted_through_sequence` with the anchored `last_sequence`.
3. A difference means DB-side truncation or alteration (`MISSING_EVENT` / `CHECKPOINT_MISMATCH`). Preserve the DB snapshot and treat it as a database-integrity incident.

## Signing-key compromise
See `docs/cryptography/TRUST_MODEL.md`.
- Stop signing.
- Distribute the updated trust store.
- Rely only on checkpoints anchored before the compromise window.

## Tenant data exposure
- Identify the token and scopes involved from API logs.
- Revoke it at the IdP.
- Confirm RLS by running `tests/integration/test_kernel.py::test_rls_*` against a snapshot.
- Notify per contractual obligations.

## Policy bypass
- Query `policy_decisions` for `allow` decisions on tools without grants.
- Diff the deployed Rego against the repository.
- Run `aegistrace policy test`.
- Deploy a fix, then re-check affected runs' `tool.authorization` events.

## Database corruption
- Fail over or restore (RUNBOOK).
- Run `verify_restored.py` with the anchor.
- Runs reported `MISSING_EVENT` lost data in the restore window and need manual reconciliation.

## Queue backlog
- Check `aegis_queue_pending_messages` and `aegis_outbox_lag_seconds`.
- Scale workers.
- Messages are safe to redeliver. Dead letters go to `aegis:runs:dead`.

## External tool compromise
- Revoke grants for the tool (`PUT /v1/agents/{id}/grants` with a lower class, or delete it).
- Runs with an unknown outcome are in `NEEDS_RECONCILIATION`; reconcile each one with the provider before choosing an outcome.

## Dependency vulnerability
- Run `pip-audit`, `npm audit` and Trivy.
- Patch, rebuild, rescan.
- If exploitable in the deployment threat model and Critical/High: release block (§48).
