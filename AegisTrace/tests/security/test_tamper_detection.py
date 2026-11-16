# SPDX-License-Identifier: FSL-1.1-ALv2
# Copyright 2026 AegisTrace contributors
"""Release gate C: tampering with a receipt must be detected offline."""

import base64
import json

from aegistrace.evidence.bundle import write_bundle
from aegistrace.evidence.checkpoint import CheckpointBody, sign_checkpoint
from aegistrace.evidence.signing import LocalEd25519Signer
from aegistrace.evidence.trust import TrustStore
from aegistrace.evidence.verifier import Status, verify_bundle
from tests.conftest import RUN, TENANT, build_run, edit_events, repack, trust_doc, unpack


def verify(bundle, trust, tenant=TENANT, run=RUN):
    return verify_bundle(bundle, trust, tenant, run)


def test_untampered_bundle_is_valid(run):
    r = verify(run.bundle, run.trust)
    assert r.status is Status.VALID, r.as_dict()
    assert r.trusted_through_sequence == r.event_count == 5


def test_payload_mutation(run):
    def mutate(evs):
        evs[1]["payload"]["doc"] = "secret-plans"
        return evs

    assert verify(edit_events(run.bundle, mutate), run.trust).status is Status.PAYLOAD_MISMATCH


def test_payload_mutation_with_recomputed_digest_breaks_hash(run):
    from aegistrace.evidence.events import payload_digest

    def mutate(evs):
        evs[1]["payload"]["doc"] = "x"
        evs[1]["payload_digest"] = payload_digest(evs[1]["payload"])
        return evs

    assert verify(edit_events(run.bundle, mutate), run.trust).status is Status.INVALID_EVENT_HASH


def test_header_mutation_with_rehash_breaks_chain_and_checkpoint(run):
    """Attacker rewrites an event and recomputes every hash forward. The chain
    is self-consistent but no longer matches the signed checkpoint."""
    from aegistrace.evidence.events import Event

    def mutate(evs):
        evs[2]["actor_id"] = "attacker"
        prev = evs[1]["current_event_hash"]
        for e in evs[2:]:
            e["previous_event_hash"] = prev
            fields = {k: v for k, v in e.items() if k not in ("current_event_hash", "payload")}
            e["current_event_hash"] = prev = Event(**fields).compute_hash()
        return evs

    r = verify(edit_events(run.bundle, mutate), run.trust)
    assert r.status is Status.CHECKPOINT_MISMATCH


def test_middle_event_deletion(run):
    r = verify(edit_events(run.bundle, lambda evs: evs[:2] + evs[3:]), run.trust)
    assert r.status is Status.MISSING_EVENT


def test_tail_deletion_within_checkpoint(run):
    r = verify(edit_events(run.bundle, lambda evs: evs[:-1]), run.trust)
    assert r.status is not Status.VALID
    assert any(f.code is Status.MISSING_EVENT for f in r.findings)


def test_reordering(run):
    def swap(evs):
        evs[1], evs[2] = evs[2], evs[1]
        return evs

    assert verify(edit_events(run.bundle, swap), run.trust).status is Status.BROKEN_SEQUENCE


def test_artifact_modification(run):
    files = unpack(run.bundle)
    name = next(n for n in files if n.startswith("artifacts/"))
    files[name] = b"forged report"
    assert verify(repack(files), run.trust).status is Status.ARTIFACT_CORRUPTED


def test_invalid_signature(run):
    files = unpack(run.bundle)
    cps = json.loads(files["checkpoints.json"])
    sig = bytearray(base64.b64decode(cps[0]["signature"]))
    sig[0] ^= 1
    cps[0]["signature"] = base64.b64encode(bytes(sig)).decode()
    files["checkpoints.json"] = json.dumps(cps).encode()
    assert verify(repack(files), run.trust).status is Status.INVALID_SIGNATURE


def test_signature_substitution_by_untrusted_key(run):
    """Attacker re-signs the checkpoint with their own key."""
    attacker = LocalEd25519Signer()
    files = unpack(run.bundle)
    cps = json.loads(files["checkpoints.json"])
    body = CheckpointBody(**{**cps[0]["body"], "key_id": attacker.key_id})
    files["checkpoints.json"] = json.dumps([sign_checkpoint(body, attacker)]).encode()
    r = verify(repack(files), run.trust)
    assert r.status is Status.UNTRUSTED_SIGNER


def test_valid_signature_from_untrusted_signer_is_not_trusted():
    fx = build_run()
    other = TrustStore.from_json(trust_doc(LocalEd25519Signer()))
    assert verify(fx.bundle, other).status is Status.UNTRUSTED_SIGNER


def test_compromised_key_rejected():
    fx = build_run()
    trust = TrustStore.from_json(trust_doc(fx.signer, compromised=True))
    assert verify(fx.bundle, trust).status is Status.UNTRUSTED_SIGNER


def test_revoked_key_accepts_only_earlier_checkpoints():
    fx = build_run()
    before = TrustStore.from_json(trust_doc(fx.signer, revoked_at="2026-12-01T00:00:00Z"))
    after = TrustStore.from_json(trust_doc(fx.signer, revoked_at="2026-10-01T00:00:00Z"))
    assert verify(fx.bundle, before).status is Status.VALID
    assert verify(fx.bundle, after).status is Status.UNTRUSTED_SIGNER


def test_tenant_scoped_key_rejected_for_other_tenant():
    fx = build_run()
    trust = TrustStore.from_json(trust_doc(fx.signer, tenant_ids=["tnt_beta"]))
    assert verify(fx.bundle, trust).status is Status.UNTRUSTED_SIGNER


def test_cross_run_substitution(run):
    """A valid bundle for one run must not verify as another run."""
    assert verify(run.bundle, run.trust, run="run_002").status is Status.BINDING_MISMATCH
    assert verify(run.bundle, run.trust, tenant="tnt_beta").status is Status.BINDING_MISMATCH


def test_missing_checkpoint_reports_incomplete(run):
    files = unpack(run.bundle)
    files["checkpoints.json"] = b"[]"
    assert verify(repack(files), run.trust).status is Status.INCOMPLETE_HISTORY


def test_events_after_checkpoint_are_incomplete():
    fx = build_run()
    fx.chain.append(
        event_id="late", event_type="x", actor_id="a", correlation_id=RUN, timestamp="2026-10-31T11:00:00Z", payload={}
    )
    files = unpack(fx.bundle)
    bundle = write_bundle(TENANT, RUN, fx.chain.events, json.loads(files["checkpoints.json"]), {})
    r = verify(bundle, fx.trust)
    assert r.status is Status.INCOMPLETE_HISTORY
    assert r.trusted_through_sequence == 5


def test_redacted_payload_still_verifies(run):
    def redact(evs):
        del evs[1]["payload"]
        return evs

    r = verify(edit_events(run.bundle, redact), run.trust)
    assert r.status is Status.VALID
    assert any("withheld" in w for w in r.warnings)


def test_unsupported_schema_version(run):
    def bump(evs):
        evs[0]["schema_version"] = 99
        return evs

    assert verify(edit_events(run.bundle, bump), run.trust).status is Status.UNSUPPORTED_VERSION


def test_trusted_range_stops_at_first_failure(run):
    def swap(evs):
        evs[1], evs[2] = evs[2], evs[1]
        return evs

    assert verify(edit_events(run.bundle, swap), run.trust).trusted_through_sequence == 1


# -- external anchoring closes the tail-truncation gap --------------------------


def _truncated_with_old_checkpoint():
    """Attacker drops the newest event AND the checkpoint covering it, and
    substitutes an older genuine checkpoint that covers only the prefix."""
    from aegistrace.evidence.checkpoint import CheckpointBody, sign_checkpoint

    fx = build_run()
    head4 = fx.chain.events[3].current_event_hash
    old_cp = sign_checkpoint(
        CheckpointBody(TENANT, RUN, 1, 4, head4, fx.signer.key_id, "2026-10-31T10:01:30Z"), fx.signer
    )
    final_cp = json.loads(unpack(fx.bundle)["checkpoints.json"])[0]
    truncated = write_bundle(TENANT, RUN, fx.chain.events[:4], [old_cp], {})
    return fx, truncated, final_cp


def test_truncation_undetectable_without_anchor():
    fx, truncated, _ = _truncated_with_old_checkpoint()
    r = verify(truncated, fx.trust)
    assert r.status is Status.VALID  # the documented limitation
    assert any("no external anchor" in w for w in r.warnings)


def test_truncation_detected_with_anchor():
    fx, truncated, final_cp = _truncated_with_old_checkpoint()
    r = verify_bundle(truncated, fx.trust, TENANT, RUN, anchored_checkpoints=[final_cp])
    assert r.status is Status.MISSING_EVENT


def test_anchor_file_roundtrip(tmp_path):
    from aegistrace.evidence.anchor import FileAnchor, load_anchor

    fx, truncated, final_cp = _truncated_with_old_checkpoint()
    a = FileAnchor(tmp_path / "anchor.jsonl")
    a.publish(final_cp)
    assert (
        verify_bundle(fx.bundle, fx.trust, TENANT, RUN, anchored_checkpoints=load_anchor(a.path.read_bytes())).status
        is Status.VALID
    )
