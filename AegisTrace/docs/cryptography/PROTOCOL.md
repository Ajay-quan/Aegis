# Evidence Protocol v1 (`aegistrace.v1`)

Implementation: `packages/core/src/aegistrace/evidence/`. This document describes
what that code does today.

## Canonical encoding

RFC 8785 (JCS) over a restricted data model: objects with string keys, arrays,
strings, booleans, null, and integers in ±(2^53−1). **Floats are rejected**
(encode decimals as strings). Lone surrogates are rejected. Keys are sorted by
UTF-16 code units. Nesting depth ≤ 64. Parsing for verification
(`strict_loads`) rejects duplicate keys, floats, NaN and Infinity.

## Digests (all SHA-256, rendered `sha256:<hex>`)

Every digest is domain-separated with a NUL-terminated ASCII prefix:

| Purpose  | Input |
|----------|-------|
| payload  | `"aegistrace.v1.payload\0" ‖ JCS(payload)` |
| artifact | `"aegistrace.v1.artifact\0" ‖ raw bytes` |
| genesis  | `"aegistrace.v1.genesis\0" ‖ JCS({protocol, tenant_id, run_id})` |
| event    | `"aegistrace.v1.event\0" ‖ JCS(event fields)` |
| checkpoint signing input | `"aegistrace.v1.checkpoint\0" ‖ JCS(checkpoint body)` |

Event hashed fields: `protocol, event_id, tenant_id, project_id, run_id,
sequence_number, event_type, schema_version, actor_id, causation_id,
correlation_id, timestamp, payload_digest, previous_event_hash`.

`current_event_hash` is not itself hashed. The payload is bound only through
`payload_digest`, so a payload can be withheld (redaction or privacy deletion)
without breaking verification.

## Chain rules

- Sequence numbers start at 1 and are contiguous per run.
- Event 1's `previous_event_hash` is the genesis hash for (tenant, run). This
  binds the chain root to its tenant and run, so it cannot be moved to another run.
- Event *n*'s `previous_event_hash` = hash of event *n−1*.

## Checkpoints

Body: `protocol, tenant_id, run_id, first_sequence (=1 in v1), last_sequence,
final_event_hash, key_id, created_at`. Signature: Ed25519 over the signing input
above. `key_id = "ed25519:" ‖ hex(SHA256(raw public key))[:32]`.

## Trust

The verifier uses a trust store **it controls**. Nothing in the bundle tells it what to trust.
A checkpoint counts only if all of these hold:

1. Its key is in the trust store.
2. The signature verifies.
3. The key is not marked compromised.
4. The key is scoped to the tenant (when scoped).
5. `created_at` is within `[not_before, not_after]` and before `revoked_at`.

`created_at` is asserted by the signer. So a compromised key could backdate a
checkpoint, and **compromised keys are therefore rejected for every checkpoint**.
Retired or revoked keys (not compromised) still validate earlier checkpoints.
External anchoring would remove this limitation, but it is not built yet.

## Receipt bundle (zip, format version 1)

The allowed entries are exactly `manifest.json`, `events.jsonl`, `checkpoints.json`, and
`artifacts/<64 hex>`.

The reader rejects:

- any other name, including traversal and absolute paths
- duplicate entries and encrypted entries
- more than 10k entries
- any entry over 64 MiB, or more than 256 MiB in total
- a compression ratio above 200:1

Decompressed size is bounded by actually reading the data, not by trusting the header.
The manifest's per-file SHA-256 values and sizes must match exactly (`MANIFEST_MISMATCH`). They catch
accidental corruption; integrity itself comes from the chain and the signed checkpoint.

## Verifier results

`VALID`, `MALFORMED_BUNDLE`, `UNSUPPORTED_VERSION`, `BINDING_MISMATCH`,
`MANIFEST_MISMATCH`, `BROKEN_SEQUENCE`, `MISSING_EVENT`, `INVALID_EVENT_HASH`,
`BROKEN_CHAIN`, `PAYLOAD_MISMATCH`, `ARTIFACT_CORRUPTED`, `INVALID_SIGNATURE`,
`UNTRUSTED_SIGNER`, `CHECKPOINT_MISMATCH`, `INCOMPLETE_HISTORY`.

`trusted_through_sequence` is the highest sequence that a trusted checkpoint
vouches for, capped just before the first failing event. `VALID` requires the
trusted range to cover every event.

**VALID means the recorded history is intact and was vouched for by a trusted
signer. It does not prove that the recorded real-world action happened.**

## External anchoring (closes tail truncation)

If an attacker removes the newest events *and* every checkpoint covering them,
the remaining prefix still verifies against an older checkpoint. Workers
therefore publish every checkpoint to an append-only **anchor**:
`FileAnchor` (JSON lines) in development, and S3 Object Lock (COMPLIANCE mode)
in a separate account in the reference AWS stack.

`aegistrace-verify --anchor anchor.jsonl` (or `anchored_checkpoints=` in the
library) evaluates anchored checkpoints with the same trust rules as bundled
ones. A trusted anchored checkpoint whose `last_sequence` exceeds the bundle's
events yields `MISSING_EVENT`.

Without an anchor, the verifier warns on every run that truncation is undetectable.

Tests: `test_truncation_undetectable_without_anchor`,
`test_truncation_detected_with_anchor`, `test_anchor_file_roundtrip`.
