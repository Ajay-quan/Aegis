# Payload encryption, erasure, legal hold and retention

## What is encrypted at rest
Content: the run's input and result, model responses, tool outputs, tool validation errors, and the
arguments shown on approval requests. Encrypted with AES-256-GCM using a **separate data key per run**.
Each ciphertext is bound to its location (table, row, field), so it cannot be moved or swapped.

Not encrypted (the platform queries these): tool names, call keys, execution ids, decisions and reasons,
risk classes, digests, hashes, error type names. Evidence (digests, hash chain, signatures) is always
computed over the plaintext, so encryption changes nothing a verifier checks.

## Keys
Per-run data keys are stored only **wrapped** by the platform key-encryption key (KEK).
- Development: `AEGIS_PAYLOAD_KEK_FILE` (32 random bytes, base64), created by `scripts/dev_bootstrap.py`.
- Production: implement `KeyWrapper` (`persistence/sealing.py`) on your KMS or HSM (wrap and unwrap with
  associated data). The KEK never leaves the KMS.

Without `AEGIS_PAYLOAD_KEK_FILE` content is stored in clear (backward compatible). Runs stored that way
cannot be crypto-shredded; the API says so.

## Erasure (crypto-shredding)
Destroying a run's wrapped data key makes all of its content permanently unreadable. Events, digests,
checkpoints and signatures are untouched: receipts still verify, with payloads reported as *withheld*.
- One run: `POST /v1/runs/{id}/erase {"reason": "..."}`, or **Erase content** on the run page.
- All finished runs of the organization: `POST /v1/data/erase {"reason", "confirm": "<tenant id>", "finished_before"?}`.
- Every erasure is logged (`GET /v1/erasures`, Security page): who, when, why, which runs. No content.
- Requires the `data:erase` scope. The database refuses to restore or delete a shredded key.

## Legal hold
`PUT /v1/runs/{id}/legal-hold {"hold": true}`, or the run page. A held run cannot be erased, by the API,
by retention, or directly in the database (trigger).

## Retention
Rules → **Erase run content after** (`payload_retention_days`). The worker applies it every 5 minutes
through one cross-tenant database function that can only shred, skips held runs, follows each
organization's own setting, and logs each erasure with scope `retention`.

## Not covered
Database backups and replicas keep wrapped keys until they expire under your backup retention policy.
Content copied out of AegisTrace (exported receipts, downstream systems) is outside its control.
