# SPDX-License-Identifier: FSL-1.1-ALv2
# Copyright 2026 AegisTrace contributors
"""Hostile archive handling: the reader must reject, never partially trust."""

import io
import zipfile

import pytest

from aegistrace.evidence.bundle import BundleError, Limits, read_bundle
from aegistrace.evidence.verifier import Status, verify_bundle
from tests.conftest import RUN, TENANT, unpack


def _zip(entries):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in entries:
            zf.writestr(name, data)
    return buf.getvalue()


@pytest.mark.parametrize(
    "name",
    ["../evil", "/etc/passwd", "artifacts/../../x", "artifacts\\..\\x", "artifacts/ABC", "extra.txt"],
)
def test_rejects_disallowed_paths(name):
    with pytest.raises(BundleError):
        read_bundle(_zip([("manifest.json", b"{}"), (name, b"x")]))


def test_rejects_duplicate_entries():
    with pytest.warns(UserWarning):  # zipfile warns on duplicate names
        data = _zip([("manifest.json", b"{}"), ("manifest.json", b"{}")])
    with pytest.raises(BundleError, match="duplicate"):
        read_bundle(data)


def test_rejects_decompression_bomb():
    data = _zip([("manifest.json", b"{}"), ("events.jsonl", b"\0" * 5_000_000)])
    with pytest.raises(BundleError, match="ratio"):
        read_bundle(data)


def test_rejects_oversized_entry():
    data = _zip([("manifest.json", b"{}"), ("events.jsonl", bytes(range(256)) * 100)])
    with pytest.raises(BundleError, match="too large"):
        read_bundle(data, Limits(max_file_bytes=1000))


def test_rejects_too_many_entries():
    entries = [("manifest.json", b"{}")] + [(f"artifacts/{i:064x}", b"x") for i in range(20)]
    with pytest.raises(BundleError, match="too many"):
        read_bundle(_zip(entries), Limits(max_entries=10))


def test_garbage_is_malformed(run):
    assert verify_bundle(b"not a zip", run.trust, TENANT, RUN).status is Status.MALFORMED_BUNDLE


def test_unlisted_file_rejected(run):
    files = unpack(run.bundle)
    files["artifacts/" + "0" * 64] = b"smuggled"
    r = verify_bundle(_zip(files.items()), run.trust, TENANT, RUN)
    assert r.status is Status.MANIFEST_MISMATCH
