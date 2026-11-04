# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 AegisTrace contributors
"""RFC 8785 (JCS) canonical JSON over a deliberately restricted data model.

Accepted types: dict (str keys), list, str, bool, None, and int within the
IEEE-754 safe range. Floats are rejected outright: JCS number serialization
of non-integers is easy to get subtly wrong across implementations, and no
evidence field needs them. Encode decimals as strings.
"""

from __future__ import annotations

import json
from typing import Any

MAX_SAFE_INT = 2**53 - 1
MAX_DEPTH = 64


class CanonicalizationError(ValueError):
    """Value cannot be represented in the canonical data model."""


def _check_string(s: str) -> None:
    for ch in s:
        if 0xD800 <= ord(ch) <= 0xDFFF:
            raise CanonicalizationError("lone surrogate in string")


def _encode(value: Any, out: list[str], depth: int) -> None:
    if depth > MAX_DEPTH:
        raise CanonicalizationError("nesting too deep")
    if value is None:
        out.append("null")
    elif value is True:
        out.append("true")
    elif value is False:
        out.append("false")
    elif isinstance(value, int):
        if abs(value) > MAX_SAFE_INT:
            raise CanonicalizationError("integer outside safe range")
        out.append(str(value))
    elif isinstance(value, str):
        _check_string(value)
        # Python's escaping matches JCS: short escapes for \b\f\n\r\t,
        # lowercase \u00XX for other controls, no escaping of non-ASCII.
        out.append(json.dumps(value, ensure_ascii=False))
    elif isinstance(value, list | tuple):
        out.append("[")
        for i, item in enumerate(value):
            if i:
                out.append(",")
            _encode(item, out, depth + 1)
        out.append("]")
    elif isinstance(value, dict):
        for k in value:
            if not isinstance(k, str):
                raise CanonicalizationError("object keys must be strings")
            _check_string(k)
        # JCS sorts keys by UTF-16 code units, not code points.
        keys = sorted(value, key=lambda k: k.encode("utf-16-be"))
        out.append("{")
        for i, k in enumerate(keys):
            if i:
                out.append(",")
            out.append(json.dumps(k, ensure_ascii=False))
            out.append(":")
            _encode(value[k], out, depth + 1)
        out.append("}")
    else:
        raise CanonicalizationError(f"unsupported type: {type(value).__name__}")


def canonicalize(value: Any) -> bytes:
    out: list[str] = []
    _encode(value, out, 0)
    return "".join(out).encode("utf-8")


def _reject_constant(name: str) -> Any:
    raise CanonicalizationError(f"non-finite number: {name}")


def _reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for k, v in pairs:
        if k in result:
            raise CanonicalizationError(f"duplicate key: {k!r}")
        result[k] = v
    return result


def strict_loads(data: bytes | str) -> Any:
    """Parse JSON rejecting duplicate keys, floats, and NaN/Infinity."""

    def no_float(s: str) -> Any:
        raise CanonicalizationError("floats are not permitted")

    return json.loads(
        data,
        object_pairs_hook=_reject_duplicates,
        parse_float=no_float,
        parse_constant=_reject_constant,
    )
