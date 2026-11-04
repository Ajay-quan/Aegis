# SPDX-License-Identifier: FSL-1.1-ALv2
# Copyright 2026 AegisTrace contributors
"""The Rego package name is the OPA query path the gateway calls. If they drift
apart, OPA returns an empty result and every tool call fails closed."""

import inspect
import re
from pathlib import Path

from aegisguard.authorization import policy

POLICY = Path(__file__).resolve().parents[2] / "packages/aegisguard/policies/aegistrace/tools.rego"


def test_rego_package_matches_gateway_query_path():
    package = re.search(r"^package ([\w.]+)$", POLICY.read_text(), re.M).group(1)
    path = re.search(r"/v1/data/([\w/]+)", inspect.getsource(policy)).group(1)
    assert package.replace(".", "/") == path
