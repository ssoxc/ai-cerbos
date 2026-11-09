"""The metrics page reads Cerbos's own decision log, and the gateway's own records apart."""

import json
from datetime import UTC, datetime, timedelta

import pytest

from app import metrics
from app.config import settings

NOW = datetime.now(UTC)


def entry(source, principal, resource, action, effect, rule=None, val=None, at=None):
    """One decision-log line in the exact shape Cerbos 0.57 writes it."""
    kind = resource["kind"]
    outputs = []
    if rule:
        outputs.append({"src": f"resource.{kind}.vdefault#{rule}", "action": action, "val": val})
    stamp = (at or NOW).strftime("%Y-%m-%dT%H:%M:%S.%f") + "123Z"  # Nanoseconds, like Cerbos.
    line = {
        "log.logger": "cerbos.audit",
        "log.kind": "decision",
        "callId": "01TEST",
        "timestamp": stamp,
        "checkResources": {
            "inputs": [
                {
                    "requestId": "r",
                    "resource": resource,
                    "principal": principal,
                    "actions": [action],
                }
            ],
            "outputs": [
                {
                    "requestId": "r",
                    "actions": {action: {"effect": effect, "policy": f"resource.{kind}.vdefault"}},
                    "resourceId": resource["id"],
                    "outputs": outputs,
                }
            ],
        },
        "auditTrail": {},
    }
    if source:
        line["metadata"] = {"x-ai-spine-source": {"values": [source]}}
    return json.dumps(line) + "\n"


KEY = {
    "id": "key:platform-demo",
    "roles": ["api_key"],
    "attr": {"team_id": "platform", "department_id": "technology", "owner_id": "alex"},
}
AGENTS_KEY = {**KEY, "id": "key:agents-demo", "attr": {**KEY["attr"], "team_id": "agents"}}


def model(id, max_tokens=256, classification="internal"):
    tier = "premium" if id == "governed-premium" else "standard"
    return {
        "kind": "model",
        "id": id,
        "attr": {"tier": tier, "max_tokens": max_tokens, "data_classification": classification},
    }


DOWNGRADED = entry(
    "litellm",
    KEY,
    model("governed-premium"),
    "invoke",
    "EFFECT_ALLOW",
    "premium-downgraded-for-other-teams",
    {"effect": "allow", "reason": "Downgraded.", "obligations": {"model": "governed-demo"}},
)
CAPPED = entry(
    "litellm",
    AGENTS_KEY,
    model("governed-premium", 1024),
    "invoke",
    "EFFECT_ALLOW",
    "premium-for-approved-teams",
    {"effect": "allow", "reason": "Capped.", "obligations": {"max_tokens": 512}},
)
UNDER_CAP = entry(
    "litellm",
    AGENTS_KEY,
    model("governed-premium", 256),
    "invoke",
    "EFFECT_ALLOW",
    "premium-for-approved-teams",
    {"effect": "allow", "reason": "Allowed.", "obligations": {"max_tokens": 256}},
)
REFUSED = entry(
    "litellm",
    KEY,
    model("governed-premium", 256, "confidential"),
    "invoke",
    "EFFECT_DENY",
    "confidential-needs-approved-team",
    {"effect": "deny", "reason": "Not approved."},
)
DEFAULT_DENY = entry(
    "litellm",
    KEY,
    {"kind": "mcp_tool", "id": "knowledge/add_note", "attr": {"tool": "add_note", "risk": "write"}},
    "call",
    "EFFECT_DENY",
)
ASSET_USE = entry(
    "gateway",
    {"id": "alex", "roles": ["developer"], "attr": {}},
    {"kind": "asset", "id": "atlas", "attr": {}},
    "use",
    "EFFECT_ALLOW",
    "team-or-owner-uses-active-agent",
    "Team members use active agents.",
)
SIMULATED = entry(
    "playground",
    {"id": "maya", "roles": ["viewer"], "attr": {}},
    {"kind": "asset", "id": "atlas", "attr": {}},
    "edit",
    "EFFECT_DENY",
)
PROBE = entry(
    "probe",
    {"id": "probe", "roles": ["probe"], "attr": {}},
    {"kind": "ai_cerbos_probe", "id": "probe", "attr": {}},
    "check",
    "EFFECT_ALLOW",
)
LINES = [DOWNGRADED, CAPPED, UNDER_CAP, REFUSED, DEFAULT_DENY, ASSET_USE, SIMULATED, PROBE]


@pytest.fixture
def log_file(tmp_path, monkeypatch):
    path = tmp_path / "decisions.log"
    monkeypatch.setattr(settings(), "cerbos_decision_log", str(path))
    metrics._logs.clear()
    yield path
    metrics._logs.clear()


def parse(line):
    return metrics.parse_entry(line, {})[0]


def test_an_entry_keeps_source_rule_reason_and_obligations():
    decision = parse(DOWNGRADED)
    assert decision.source == "litellm"
    assert decision.rule == "premium-downgraded-for-other-teams"
    assert decision.obligations == {"model": "governed-demo"}
    assert decision.principal_attr["team_id"] == "platform"
    assert decision.at.tzinfo is not None and abs(decision.at - NOW) < timedelta(seconds=1)


def test_untagged_checks_and_unmatched_rules_are_reported_honestly():
    untagged = parse(DEFAULT_DENY.replace('"metadata"', '"ignored"'))
    assert untagged.source == "untagged"
    assert untagged.rule is None and not untagged.allowed


def test_model_outcomes_follow_how_litellm_applies_obligations():
    outcomes = [
        metrics.model_outcome(parse(line)) for line in (DOWNGRADED, CAPPED, UNDER_CAP, REFUSED)
    ]
    # A max_tokens obligation that does not lower the request changes nothing.
    assert outcomes == ["downgraded", "capped", "answered", "refused"]


def test_log_is_read_incrementally_and_survives_rotation(log_file):
    log = metrics.decision_log()
    log_file.write_text(DOWNGRADED + CAPPED[:40])  # Cerbos is mid-way through a line.
    decisions, available = log.read()
    assert available and len(decisions) == 1
    with log_file.open("a") as handle:
        handle.write(CAPPED[40:])
    assert len(log.read()[0]) == 2
    log_file.rename(log_file.with_name("decisions-2026-01-01T00-00-00.000.log"))
    log_file.write_text(REFUSED)
    assert len(log.read()[0]) == 3


def test_missing_log_is_reported_not_hidden(log_file):
    decisions, available = metrics.decision_log().read()
    assert (decisions, available) == ([], False)


def test_enforcement_is_counted_apart_from_simulations(log_file, db):
    log_file.write_text("".join(LINES))
    decisions, _ = metrics.decision_log().read()
    result = metrics.cerbos_metrics(
        decisions,
        NOW - timedelta(hours=1),
        NOW + timedelta(minutes=1),
        timedelta(minutes=5),
        metrics.Names(db),
    )
    assert result["summary"]["decisions"] == 6  # Playground and probe excluded.
    assert result["summary"]["denied"] == 2
    assert result["summary"]["simulated"] == 1
    assert "probe" not in {s["source"] for s in result["sources"]}
    llm = result["litellm"]
    assert llm["outcomes"] == {"answered": 1, "downgraded": 1, "capped": 1, "refused": 1}
    assert {r["team"] for r in llm["by_team"]} == {"Platform Engineering", "Agents & Automation"}
    assert llm["tools"] == [{"tool": "add_note", "risk": "write", "allowed": 0, "denied": 1}]
    rules = {r["rule"] for r in result["top_rules"]}
    assert metrics.DEFAULT_DENY in rules and "premium-for-approved-teams" in rules
    top = result["principals"][0]
    assert top["denied"] == 2 and top["name"] == "Removed API key …m-demo"
    assert top["top_check"] in {"invoke model:governed-premium", "call mcp_tool:knowledge/add_note"}
    assert sum(b["allowed"] + b["denied"] for b in result["timeline"]) == 6


def test_old_decisions_fall_outside_the_window(log_file, db):
    old = entry(
        "api",
        {"id": "alex", "roles": ["developer"], "attr": {}},
        {"kind": "asset", "id": "atlas", "attr": {}},
        "view",
        "EFFECT_ALLOW",
        at=NOW - timedelta(days=2),
    )
    log_file.write_text(old + ASSET_USE)
    decisions, _ = metrics.decision_log().read()
    result = metrics.cerbos_metrics(
        decisions,
        NOW - timedelta(hours=24),
        NOW + timedelta(minutes=1),
        timedelta(hours=1),
        metrics.Names(db),
    )
    assert result["summary"]["decisions"] == 1


def test_only_administrative_roles_see_metrics(client, sign_in, log_file):
    log_file.write_text("".join(LINES))
    sign_in("maya")
    assert client.get("/api/metrics").status_code == 403
    sign_in("morgan")
    response = client.get("/api/metrics?window=1h")
    assert response.status_code == 200
    body = response.json()
    assert body["cerbos"]["available"] is True
    assert body["cerbos"]["litellm"]["model_calls"] == 4
    assert body["ledger"]["summary"]["requests"] == 0
    assert client.get("/api/metrics?window=1y").status_code == 422


def test_platform_permission_is_reported_to_the_dashboard(client, sign_in):
    sign_in("morgan")
    assert client.get("/api/state").json()["permissions"]["view_metrics"] is True
    sign_in("alex")
    assert client.get("/api/state").json()["permissions"]["view_metrics"] is False
