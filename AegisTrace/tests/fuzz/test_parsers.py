# SPDX-License-Identifier: FSL-1.1-ALv2
# Copyright 2026 AegisTrace contributors
"""Property-based fuzzing of hostile-input parsers. Invariant: never crash
with an unexpected exception, never return VALID for corrupted input."""

from __future__ import annotations

import contextlib
import io
import json
import zipfile

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from aegistrace.evidence.anchor import load_anchor
from aegistrace.evidence.bundle import BundleError, read_bundle
from aegistrace.evidence.canonical import CanonicalizationError, strict_loads
from aegistrace.evidence.verifier import Status, verify_bundle
from aegistrace.replay.engine import ReplayError, reconstruct, replay_decisions
from tests.conftest import RUN, TENANT, build_run, unpack

FX = build_run()
FILES = unpack(FX.bundle)
FUZZ = settings(max_examples=150, deadline=None, suppress_health_check=[HealthCheck.too_slow])


@FUZZ
@given(st.binary(max_size=4096))
def test_bundle_reader_rejects_garbage_cleanly(data):
    with contextlib.suppress(BundleError):
        read_bundle(data)


@FUZZ
@given(st.binary(max_size=2048))
def test_verifier_total_on_garbage(data):
    assert verify_bundle(data, FX.trust, TENANT, RUN).status is not Status.VALID


@FUZZ
@given(st.sampled_from(sorted(FILES)), st.integers(0, 10_000), st.integers(1, 255))
def test_any_byte_flip_in_any_file_is_detected(name, pos, xor):
    files = dict(FILES)
    content = bytearray(files[name])
    if not content:
        return
    content[pos % len(content)] ^= xor
    files[name] = bytes(content)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for n, b in files.items():
            zf.writestr(n, b)
    assert verify_bundle(buf.getvalue(), FX.trust, TENANT, RUN).status is not Status.VALID


@FUZZ
@given(st.text(max_size=512))
def test_strict_loads_total(s):
    with contextlib.suppress(CanonicalizationError, ValueError):
        strict_loads(s)


@FUZZ
@given(st.binary(max_size=2048))
def test_anchor_loader_total(data):
    with contextlib.suppress(CanonicalizationError, ValueError):
        load_anchor(data)


event_like = st.fixed_dictionaries(
    {
        "sequence_number": st.integers(-2, 10),
        "schema_version": st.sampled_from([1, 2, None]),
        "event_type": st.sampled_from(
            [
                "run.created",
                "run.state_changed",
                "model.invoked",
                "tool.denied",
                "tool.execution_succeeded",
                "approval.decided",
                "x",
            ]
        ),
    },
    optional={
        "payload": st.one_of(
            st.none(),
            st.dictionaries(
                st.sampled_from(
                    ["to", "step", "response", "output", "reason", "error", "approval_id", "decision", "input"]
                ),
                st.one_of(st.integers(), st.text(max_size=5), st.none()),
                max_size=4,
            ),
        )
    },
)


@FUZZ
@given(st.lists(event_like, max_size=8))
def test_replay_total_on_arbitrary_streams(records):
    try:
        reconstruct(records)
    except ReplayError:
        pass
    except (KeyError, TypeError, AttributeError, ValueError) as exc:
        raise AssertionError(f"replay crashed: {exc!r}") from exc
    try:
        replay_decisions(records)
    except (KeyError, TypeError, AttributeError, ValueError) as exc:
        raise AssertionError(f"decision replay crashed: {exc!r}") from exc


def test_fixture_valid():
    assert verify_bundle(FX.bundle, FX.trust, TENANT, RUN).status is Status.VALID
    assert json.loads(FILES["manifest.json"])["version"] == 1
