"""The AI traffic board's story, checked against the shipped policies without LiteLLM.

The real board (POST /api/playground/traffic) sends these calls through the gateway and
LiteLLM; scripts/smoke.py asserts that the live outcomes match EXPECTED below.
"""

import pytest

from app.gateway import model_resource
from app.playground import MCP_TOOLS, SITUATIONS, demo_key_principal, mcp_tool_resource
from app.policy import explain

EXPECTED = {
    "standard": {"alex": "answered", "sam": "answered", "riley": "answered"},
    "premium": {"alex": "downgraded", "sam": "answered", "riley": "downgraded"},
    "premium-long": {"alex": "downgraded", "sam": "capped", "riley": "downgraded"},
    "confidential": {"alex": "refused", "sam": "answered", "riley": "refused"},
    "bypass": {"alex": "refused", "sam": "refused", "riley": "refused"},
    "bypass-billed": {"alex": "answered", "sam": "answered", "riley": "answered"},
    "streamed": {"alex": "answered", "sam": "answered", "riley": "answered"},
    "catalog": {"alex": "hidden", "sam": "listed", "riley": "hidden"},
    "mcp-read": {"alex": "called", "sam": "called", "riley": "called"},
    "mcp-write": {"alex": "refused", "sam": "called", "riley": "refused"},
    "mcp-destructive": {"alex": "refused", "sam": "refused", "riley": "refused"},
}
PREMIUM_CAP = 512


def predict(db, situation, owner):
    principal = demo_key_principal(db, owner)
    if "request" in situation:
        request = situation["request"]
        item = model_resource(
            request["model"], request["max_tokens"], request["data_classification"]
        )
        decision = explain(principal, [item], ["invoke"])[item["id"]]["invoke"]
        if decision["effect"] == "deny":
            return "refused"
        if decision["rule"] == "premium-downgraded-for-other-teams":
            return "downgraded"
        if request["model"] == "governed-premium" and request["max_tokens"] > PREMIUM_CAP:
            return "capped"
        return "answered"
    if situation["id"] == "catalog":
        item = model_resource("governed-premium", 1, "public")
        decision = explain(principal, [item], ["list"])[item["id"]]["list"]
        return "listed" if decision["effect"] == "allow" else "hidden"
    tool = next(t for t in MCP_TOOLS if t["name"] == situation["tool"])
    item = mcp_tool_resource(tool)
    decision = explain(principal, [item], ["call"])[item["id"]]["call"]
    return "called" if decision["effect"] == "allow" else "refused"


def test_board_covers_every_situation():
    assert [s["id"] for s in SITUATIONS] == list(EXPECTED)


@pytest.mark.parametrize("situation", SITUATIONS, ids=[s["id"] for s in SITUATIONS])
def test_situation_outcomes_per_key(db, situation):
    predicted = {owner: predict(db, situation, owner) for owner in ("alex", "sam", "riley")}
    assert predicted == EXPECTED[situation["id"]]
