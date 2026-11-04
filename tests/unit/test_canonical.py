# SPDX-License-Identifier: FSL-1.1-ALv2
# Copyright 2026 AegisTrace contributors
import pytest

from aegistrace.evidence.canonical import CanonicalizationError, canonicalize, strict_loads


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ({"b": 1, "a": [True, None, "x"]}, b'{"a":[true,null,"x"],"b":1}'),
        # RFC 8785 §3.2.3: keys sorted by UTF-16 code units. U+1F600 (surrogate
        # pair D83D..) sorts before U+FB01 even though its code point is larger.
        ({"ﬁ": 1, "\U0001f600": 2}, '{"\U0001f600":2,"ﬁ":1}'.encode()),
        ({"s": '€$\u000f\nA\'B"\\\\"/'}, b'{"s":"\xe2\x82\xac$\\u000f\\nA\'B\\"\\\\\\\\\\"/"}'),
        ([], b"[]"),
        ({}, b"{}"),
        (-(2**53 - 1), b"-9007199254740991"),
    ],
)
def test_vectors(value, expected):
    assert canonicalize(value) == expected


@pytest.mark.parametrize("bad", [1.5, 2**53, {1: "x"}, "\ud800", b"bytes", {"x": set()}])
def test_rejects_unsupported(bad):
    with pytest.raises(CanonicalizationError):
        canonicalize(bad)


@pytest.mark.parametrize("doc", ['{"a":1,"a":2}', '{"a":1.0}', '{"a":NaN}', "[Infinity]"])
def test_strict_loads_rejects(doc):
    with pytest.raises(CanonicalizationError):
        strict_loads(doc)
