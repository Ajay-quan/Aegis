# Checkpoint signing keys

## Where keys live
Only the **signing service** (`aegistrace-signer`, compose service `signer`) holds private keys. It has
**no network** (`network_mode: none`). The API and workers reach it through a Unix socket on a shared
volume (`AEGIS_SIGNER_SOCKET`) and never see a key. The service:
- signs **checkpoint bodies only** (domain-separated input); anything else is refused, so a compromised
  API or worker cannot use it to sign arbitrary data;
- returns signatures the client verifies against the published public key before using them.

Keys are kept in a key ring directory (`<id>.pem`, mode 0600; `ring.json`) with exactly one active key.

## Rotation
`./aegis rotate-keys` (or `aegistrace-signer rotate --keys DIR`):
1. creates a new active key;
2. retires the old one, which may still sign for **5 minutes** so in-flight checkpoints complete;
3. regenerates the trust store (`aegistrace-signer trust-store`). The old key gets `not_after` = retirement
   + 5 minutes, so verifiers accept it only for checkpoints made before that.

Old receipts keep verifying. Tested: a live rotation on the running stack, then 7,571 / 7,571 finished
runs VALID across both keys.

## Trust distribution to verifiers
Verifiers (auditors, customers) need the trust store (`.dev/trust.json` locally), obtained **out of band**:
a signed release asset, your security portal, or another channel the verifier already trusts. Never fetch
it from the system being verified. Publish the new trust store before the grace period ends. A
compromised key is marked `"compromised": true`; verifiers then reject everything it signed unless an
external anchor proves otherwise.

## Production
Run the signing service on an isolated host, or put the key ring in an HSM or KMS that supports
**Ed25519**. Check that support before choosing a provider; Ed25519 availability differs by KMS and
region. The protocol between API/worker and signer stays the same.

Remaining: an HSM/KMS backend implementation (needs a provider account to test).
