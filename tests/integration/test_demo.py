"""The demo's checks as tests: run after `make demo` (or `make up && make simulate`)."""

import demo
import pytest

from omics.cli import scenario_files, settle

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module", autouse=True)
def settled():
    try:
        settle(scenario_files(), timeout=0)
    except Exception as exc:  # stack down, or scenario not (fully) processed yet
        pytest.skip(f"scenario not settled: {exc}")


@pytest.mark.parametrize(("topic", "fn"), demo.CHECKS, ids=[topic for topic, _ in demo.CHECKS])
def test_demo_check(topic, fn):
    passed, evidence = fn()
    assert passed, f"{topic}: {evidence}"
