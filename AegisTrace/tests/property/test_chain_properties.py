# SPDX-License-Identifier: FSL-1.1-ALv2
# Copyright 2026 AegisTrace contributors
import json

from hypothesis import given, settings
from hypothesis import strategies as st

from aegistrace.evidence.canonical import canonicalize, strict_loads
from aegistrace.evidence.verifier import Status, verify_bundle
from tests.conftest import RUN, TENANT, build_run, edit_events

json_values = st.recursive(
    st.none()
    | st.booleans()
    | st.integers(-(2**53 - 1), 2**53 - 1)
    | st.text().filter(lambda s: not any(0xD800 <= ord(c) <= 0xDFFF for c in s)),
    lambda children: (
        st.lists(children, max_size=4)
        | st.dictionaries(
            st.text(max_size=8).filter(lambda s: not any(0xD800 <= ord(c) <= 0xDFFF for c in s)), children, max_size=4
        )
    ),
    max_leaves=20,
)


@given(json_values)
def test_canonical_roundtrip_is_fixed_point(v):
    c = canonicalize(v)
    assert canonicalize(strict_loads(c)) == c


@given(st.dictionaries(st.text(max_size=5), st.integers(0, 9), max_size=6))
def test_key_order_does_not_matter(d):
    assert canonicalize(d) == canonicalize(dict(reversed(list(d.items()))))


FX = build_run(n_tool_events=4)
N = len(FX.chain.events)
FIELDS = ["event_id", "actor_id", "event_type", "timestamp", "correlation_id", "project_id"]


@settings(max_examples=60, deadline=None)
@given(st.integers(0, N - 1), st.sampled_from(FIELDS), st.text(min_size=1, max_size=6))
def test_any_single_field_mutation_is_detected(idx, field, suffix):
    def mutate(evs):
        evs[idx][field] = evs[idx][field] + suffix
        return evs

    assert verify_bundle(edit_events(FX.bundle, mutate), FX.trust, TENANT, RUN).status is not Status.VALID


@settings(max_examples=40, deadline=None)
@given(st.permutations(list(range(N))))
def test_any_non_identity_permutation_is_detected(perm):
    out = edit_events(FX.bundle, lambda evs: [evs[i] for i in perm])
    status = verify_bundle(out, FX.trust, TENANT, RUN).status
    assert (status is Status.VALID) == (perm == list(range(N)))


@settings(max_examples=30, deadline=None)
@given(st.sets(st.integers(0, N - 1), min_size=1, max_size=N - 1))
def test_any_deletion_is_detected(removed):
    out = edit_events(FX.bundle, lambda evs: [e for i, e in enumerate(evs) if i not in removed])
    assert verify_bundle(out, FX.trust, TENANT, RUN).status is not Status.VALID


def test_fixture_is_valid():
    assert verify_bundle(FX.bundle, FX.trust, TENANT, RUN).status is Status.VALID
    assert json.loads  # keep import used
