# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 AegisTrace contributors
"""Offline receipt verifier (INV-010).

Depends only on the bundle bytes, a verifier-supplied trust store, and the
expected tenant/run. It never contacts AegisTrace and never trusts values in
the bundle to tell it what to trust.

A VALID result means the recorded history is intact and vouched for by a
trusted signer. It does not prove that any real-world action occurred.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from .bundle import DEFAULT_LIMITS, FORMAT, FORMAT_VERSION, BundleError, Limits, read_bundle
from .canonical import CanonicalizationError, strict_loads
from .checkpoint import CheckpointBody
from .events import PROTOCOL_VERSION, Event, artifact_digest, genesis_hash, payload_digest
from .signing import unb64, verify_signature
from .trust import TrustStore


class Status(StrEnum):
    VALID = "VALID"
    MALFORMED_BUNDLE = "MALFORMED_BUNDLE"
    UNSUPPORTED_VERSION = "UNSUPPORTED_VERSION"
    BINDING_MISMATCH = "BINDING_MISMATCH"
    MANIFEST_MISMATCH = "MANIFEST_MISMATCH"
    BROKEN_SEQUENCE = "BROKEN_SEQUENCE"
    MISSING_EVENT = "MISSING_EVENT"
    INVALID_EVENT_HASH = "INVALID_EVENT_HASH"
    BROKEN_CHAIN = "BROKEN_CHAIN"
    PAYLOAD_MISMATCH = "PAYLOAD_MISMATCH"
    ARTIFACT_CORRUPTED = "ARTIFACT_CORRUPTED"
    INVALID_SIGNATURE = "INVALID_SIGNATURE"
    UNTRUSTED_SIGNER = "UNTRUSTED_SIGNER"
    CHECKPOINT_MISMATCH = "CHECKPOINT_MISMATCH"
    INCOMPLETE_HISTORY = "INCOMPLETE_HISTORY"


@dataclass
class Finding:
    code: Status
    detail: str
    sequence: int | None = None

    def as_dict(self) -> dict[str, Any]:
        return {"code": self.code.value, "detail": self.detail, "sequence": self.sequence}


@dataclass
class Report:
    status: Status
    findings: list[Finding] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    event_count: int = 0
    trusted_through_sequence: int = 0
    trusted_key_ids: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "event_count": self.event_count,
            "trusted_through_sequence": self.trusted_through_sequence,
            "trusted_key_ids": self.trusted_key_ids,
            "findings": [f.as_dict() for f in self.findings],
            "warnings": self.warnings,
            "scope": "Integrity of recorded history only; does not prove real-world effects.",
        }


_EVENT_FIELDS: dict[str, type | tuple[type, ...]] = {
    "event_id": str,
    "tenant_id": str,
    "project_id": str,
    "run_id": str,
    "sequence_number": int,
    "event_type": str,
    "schema_version": int,
    "actor_id": str,
    "causation_id": (str, type(None)),
    "correlation_id": str,
    "timestamp": str,
    "payload_digest": str,
    "previous_event_hash": str,
    "protocol": str,
}
_RECORD_FIELDS = set(_EVENT_FIELDS) | {"current_event_hash", "payload"}

SUPPORTED_SCHEMA_VERSIONS = {1}


def _fail(code: Status, detail: str, seq: int | None = None) -> Report:
    return Report(status=code, findings=[Finding(code, detail, seq)])


def _collect_artifact_refs(value: Any, out: set[str]) -> None:
    if isinstance(value, dict):
        for k, v in value.items():
            if k == "artifact_digest" and isinstance(v, str):
                out.add(v)
            else:
                _collect_artifact_refs(v, out)
    elif isinstance(value, list):
        for v in value:
            _collect_artifact_refs(v, out)


def verify_bundle(
    data: bytes,
    trust: TrustStore,
    expected_tenant_id: str,
    expected_run_id: str,
    limits: Limits = DEFAULT_LIMITS,
    anchored_checkpoints: list[dict[str, Any]] | None = None,
) -> Report:
    """anchored_checkpoints: signed checkpoints obtained independently of the
    bundle (an external anchor). Trusted ones for this run set a floor on how
    much history the bundle must contain."""
    # -- structure ---------------------------------------------------------
    try:
        raw = read_bundle(data, limits)
        manifest = strict_loads(raw.files["manifest.json"])
    except (BundleError, CanonicalizationError, ValueError) as exc:
        return _fail(Status.MALFORMED_BUNDLE, str(exc))
    if not isinstance(manifest, dict) or manifest.get("format") != FORMAT:
        return _fail(Status.MALFORMED_BUNDLE, "not an AegisTrace receipt")
    if manifest.get("version") != FORMAT_VERSION:
        return _fail(Status.UNSUPPORTED_VERSION, f"bundle version {manifest.get('version')!r}")
    if manifest.get("tenant_id") != expected_tenant_id or manifest.get("run_id") != expected_run_id:
        return _fail(Status.BINDING_MISMATCH, "bundle is not for the expected tenant/run")

    listed = manifest.get("files")
    if not isinstance(listed, list):
        return _fail(Status.MALFORMED_BUNDLE, "manifest files must be a list")
    listed_paths = set()
    for entry in listed:
        if not isinstance(entry, dict) or not isinstance(entry.get("path"), str):
            return _fail(Status.MALFORMED_BUNDLE, "bad manifest entry")
        path = entry["path"]
        if path in listed_paths:
            return _fail(Status.MALFORMED_BUNDLE, f"duplicate manifest entry {path!r}")
        listed_paths.add(path)
        content = raw.files.get(path)
        if content is None:
            return _fail(Status.MANIFEST_MISMATCH, f"listed file missing: {path}")
        if entry.get("size") != len(content):
            return _fail(Status.MANIFEST_MISMATCH, f"file size mismatch: {path}")
        if hashlib.sha256(content).hexdigest() != entry.get("sha256"):
            # A modified artifact is reported by the chain-bound artifact check
            # below as ARTIFACT_CORRUPTED; an intact file with a wrong manifest
            # entry is a manifest inconsistency.
            name = path.removeprefix("artifacts/")
            if not path.startswith("artifacts/") or artifact_digest(content) == "sha256:" + name:
                return _fail(Status.MANIFEST_MISMATCH, f"file digest mismatch: {path}")
    unlisted = set(raw.files) - listed_paths - {"manifest.json"}
    if unlisted:
        return _fail(Status.MANIFEST_MISMATCH, f"unlisted files: {sorted(unlisted)}")
    for required in ("events.jsonl", "checkpoints.json"):
        if required not in raw.files:
            return _fail(Status.MALFORMED_BUNDLE, f"missing {required}")

    # -- events ------------------------------------------------------------
    records: list[dict[str, Any]] = []
    try:
        for line in raw.files["events.jsonl"].splitlines():
            if line.strip():
                records.append(strict_loads(line))
    except (CanonicalizationError, ValueError) as exc:
        return _fail(Status.MALFORMED_BUNDLE, f"events.jsonl: {exc}")

    report = Report(status=Status.VALID, event_count=len(records))
    findings = report.findings
    events: list[Event] = []
    hashes: list[str] = []
    artifact_refs: set[str] = set()

    # A permutation of 1..n is a reordering; anything else with fewer distinct
    # sequence numbers than the maximum is a gap.
    seqs = [r.get("sequence_number") if isinstance(r, dict) else None for r in records]
    int_seqs = [s for s in seqs if isinstance(s, int) and not isinstance(s, bool)]
    is_permutation = sorted(int_seqs) == list(range(1, len(records) + 1))
    has_duplicates = len(set(int_seqs)) != len(int_seqs)

    for idx, rec in enumerate(records):
        if not isinstance(rec, dict) or set(rec) - _RECORD_FIELDS or not set(_EVENT_FIELDS) <= set(rec):
            return _fail(Status.MALFORMED_BUNDLE, "event has missing or unknown fields", idx + 1)
        for name, typ in _EVENT_FIELDS.items():
            val = rec[name]
            if not isinstance(val, typ) or (typ is int and isinstance(val, bool)):
                return _fail(Status.MALFORMED_BUNDLE, f"field {name} has wrong type", idx + 1)
        if not isinstance(rec.get("current_event_hash"), str):
            return _fail(Status.MALFORMED_BUNDLE, "missing current_event_hash", idx + 1)
        if rec["protocol"] != PROTOCOL_VERSION or rec["schema_version"] not in SUPPORTED_SCHEMA_VERSIONS:
            return _fail(Status.UNSUPPORTED_VERSION, "unsupported event protocol/schema", idx + 1)
        ev = Event(**{k: rec[k] for k in _EVENT_FIELDS})
        seq = ev.sequence_number
        if ev.tenant_id != expected_tenant_id or ev.run_id != expected_run_id:
            findings.append(Finding(Status.BINDING_MISMATCH, "event bound to another tenant/run", seq))
        expected_seq = idx + 1
        if seq != expected_seq:
            gap = not is_permutation and not has_duplicates
            code = Status.MISSING_EVENT if gap else Status.BROKEN_SEQUENCE
            findings.append(Finding(code, f"expected sequence {expected_seq}, found {seq}", seq))
        computed = ev.compute_hash()
        if computed != rec["current_event_hash"]:
            findings.append(Finding(Status.INVALID_EVENT_HASH, "event hash does not match contents", seq))
        prev = hashes[-1] if hashes else genesis_hash(expected_tenant_id, expected_run_id)
        if ev.previous_event_hash != prev:
            findings.append(Finding(Status.BROKEN_CHAIN, "previous_event_hash does not link", seq))
        if "payload" in rec:
            try:
                if payload_digest(rec["payload"]) != ev.payload_digest:
                    findings.append(Finding(Status.PAYLOAD_MISMATCH, "payload does not match digest", seq))
                else:
                    _collect_artifact_refs(rec["payload"], artifact_refs)
            except CanonicalizationError as exc:
                findings.append(Finding(Status.PAYLOAD_MISMATCH, f"payload not canonicalizable: {exc}", seq))
        else:
            report.warnings.append(f"event {seq}: payload withheld; only its digest is verified")
        events.append(ev)
        # Chain continues from the *computed* hash, so a mutated event also
        # breaks the link of the event after it.
        hashes.append(computed)

    # -- artifacts ---------------------------------------------------------
    present = {p.removeprefix("artifacts/"): c for p, c in raw.files.items() if p.startswith("artifacts/")}
    for name, content in present.items():
        if artifact_digest(content) != "sha256:" + name:
            findings.append(Finding(Status.ARTIFACT_CORRUPTED, f"artifact {name[:16]}… content mismatch"))
    for ref in sorted(artifact_refs):
        if ref.removeprefix("sha256:") not in present:
            report.warnings.append(f"referenced artifact {ref[:23]}… not included in bundle")

    # -- checkpoints -------------------------------------------------------
    try:
        checkpoints = strict_loads(raw.files["checkpoints.json"])
        if not isinstance(checkpoints, list):
            raise ValueError("checkpoints.json must be a list")
    except (CanonicalizationError, ValueError) as exc:
        return _fail(Status.MALFORMED_BUNDLE, f"checkpoints.json: {exc}")

    # Anchored checkpoints are evaluated with the same rules as bundled ones,
    # but they are also required to be satisfied by the bundle.
    anchored = [
        cp
        for cp in (anchored_checkpoints or [])
        if isinstance(cp, dict)
        and isinstance(cp.get("body"), dict)
        and cp["body"].get("tenant_id") == expected_tenant_id
        and cp["body"].get("run_id") == expected_run_id
    ]
    trusted_through = 0
    for cp in [*checkpoints, *anchored]:
        try:
            body = CheckpointBody(**cp["body"])
            sig = unb64(cp["signature"])
            if not all(isinstance(getattr(body, f), int) for f in ("first_sequence", "last_sequence")):
                raise TypeError("sequence fields must be integers")
        except (KeyError, TypeError, ValueError) as exc:
            findings.append(Finding(Status.MALFORMED_BUNDLE, f"bad checkpoint: {exc}"))
            continue
        if body.protocol != PROTOCOL_VERSION:
            findings.append(Finding(Status.UNSUPPORTED_VERSION, "unsupported checkpoint protocol"))
            continue
        key = trust.get(body.key_id)
        if key is None:
            findings.append(Finding(Status.UNTRUSTED_SIGNER, f"unknown signer {body.key_id}"))
            continue
        if not verify_signature(key.public_key_raw, sig, body.signing_input()):
            findings.append(Finding(Status.INVALID_SIGNATURE, f"bad signature by {body.key_id}"))
            continue
        problem = trust.acceptance_problem(key, body.tenant_id, body.created_at)
        if problem:
            findings.append(Finding(Status.UNTRUSTED_SIGNER, f"{body.key_id}: {problem}"))
            continue
        if body.tenant_id != expected_tenant_id or body.run_id != expected_run_id:
            findings.append(Finding(Status.CHECKPOINT_MISMATCH, "checkpoint for another tenant/run"))
            continue
        if body.first_sequence != 1 or body.last_sequence < 1:
            findings.append(Finding(Status.CHECKPOINT_MISMATCH, "v1 checkpoints must cover from sequence 1"))
            continue
        if body.last_sequence > len(hashes):
            findings.append(
                Finding(
                    Status.MISSING_EVENT,
                    f"trusted checkpoint covers {body.last_sequence} events, bundle has {len(hashes)}",
                    body.last_sequence,
                )
            )
            continue
        if hashes[body.last_sequence - 1] != body.final_event_hash:
            findings.append(
                Finding(Status.CHECKPOINT_MISMATCH, "final_event_hash does not match chain", body.last_sequence)
            )
            continue
        trusted_through = max(trusted_through, body.last_sequence)
        if body.key_id not in report.trusted_key_ids:
            report.trusted_key_ids.append(body.key_id)

    # A checkpoint matching the final hash does not vouch for events whose own
    # integrity checks failed; trust stops before the first failing sequence.
    failing = [f.sequence for f in findings if f.sequence is not None]
    if failing:
        trusted_through = max(0, min(trusted_through, min(failing) - 1))
    report.trusted_through_sequence = trusted_through
    if findings:
        report.status = findings[0].code
    elif trusted_through < len(hashes) or not hashes:
        report.status = Status.INCOMPLETE_HISTORY
        findings.append(
            Finding(Status.INCOMPLETE_HISTORY, f"trusted checkpoint covers {trusted_through} of {len(hashes)} events")
        )
    if anchored_checkpoints is None:
        report.warnings.append(
            "no external anchor supplied; truncation of the newest events together with "
            "their checkpoints is detectable only if you know which checkpoint to expect"
        )
    elif not anchored:
        report.warnings.append("anchor contains no checkpoint for this run")
    return report
