"""Every guided scenario in the playground decides exactly as its story says."""

import pytest

from app.playground import CheckRequest, run_check
from app.scenarios import SCENARIOS

CHECKS = [
    pytest.param(check, id=f"{scenario['id']}: {check['label']}")
    for scenario in SCENARIOS
    for check in scenario.get("checks", [])
]


@pytest.mark.parametrize("check", CHECKS)
def test_scenario_check_matches_the_shipped_policies(db, check):
    request = CheckRequest(
        principal=check["principal"],
        kind=check["kind"],
        resource_ids=check["resource_ids"],
        resource_overrides=check.get("resource_overrides", {}),
        actions=check["actions"],
    )
    result = run_check(db, request)
    for item in result["results"]:
        expected = check.get("expect_by_resource", {}).get(item["id"], check.get("expect"))
        actual = {action: decision["effect"] for action, decision in item["decisions"].items()}
        assert actual == expected, item["decisions"]
        for decision in item["decisions"].values():
            # Every decision is explained: a named rule, or Cerbos's default deny.
            assert decision["reason"]
            assert decision["rule"] or decision["effect"] == "deny"


def test_every_scenario_is_runnable_in_the_dashboard():
    for scenario in SCENARIOS:
        assert scenario["title"] and scenario["story"]
        assert scenario.get("checks") or scenario.get("trace")
