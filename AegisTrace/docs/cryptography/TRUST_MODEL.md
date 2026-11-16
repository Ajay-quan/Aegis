# Signing trust model and key lifecycle

## Who trusts what

- **Verifiers trust only their own trust store** (a JSON file obtained out of band) and, optionally, an anchor they read from storage they trust. Nothing in a bundle can add a trusted key.
- **A valid signature is not trust.** The key must be:
  - listed in the trust store
  - within `not_before`/`not_after`
  - not revoked as of the checkpoint time
  - not compromised
  - scoped to the tenant, if a tenant scope is set
- **The `/v1/signing-keys` endpoint is a convenience only.** An attacker who controls the API could serve a different key.
- **The dashboard's "server-side integrity check"** verifies against the server's own key and is labelled *not independent*.

## Lifecycle

| Step | Today | Production intent |
|---|---|---|
| Generation | `scripts/dev_bootstrap.py` writes a PEM (dev) | Key ceremony on a KMS/HSM. Verify that the provider supports Ed25519 before choosing it (open issue). |
| Identifier | `ed25519:` + first 32 hex characters of SHA-256 of the raw public key | same |
| Activation | Add to the trust store with `not_before` | Signed trust-store releases |
| Rotation | Add a new key, then switch the signer; old key gets `not_after` | Automated, with overlap |
| Retirement | Set `not_after`. Earlier checkpoints remain valid. | same |
| Revocation | Set `revoked_at`. Checkpoints dated at or after it are rejected. | same |
| Compromise | Set `compromised: true`. **All** checkpoints by that key are rejected, because `created_at` is signer-asserted and could be backdated. | Re-establish history from anchored checkpoints published before the compromise window: anchor timestamps come from storage the attacker did not control. |

## Compromise response

1. Stop the signer: rotate the secret, restart workers. Workers refuse to start without a key.
2. Mark the key `compromised` in all distributed trust stores.
3. Re-checkpoint affected runs with the new key **only after** re-verifying their chains against anchored checkpoints.
4. Treat any run whose newest trusted anchored checkpoint precedes the compromise as having unverifiable tail history.

See `docs/operations/INCIDENT_RESPONSE.md`.
