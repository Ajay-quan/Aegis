"""aegis-bench gates run as part of the test suite: a regression fails the build."""
import json

import pytest

from bench.run import THRESHOLDS, check
from bench.suites import SUITES

GATES = json.loads(THRESHOLDS.read_text())


@pytest.mark.parametrize("suite", list(SUITES))
async def test_suite_meets_gates(suite):
    metrics = await SUITES[suite]()
    assert check(metrics, GATES.get(suite, {})) == []
