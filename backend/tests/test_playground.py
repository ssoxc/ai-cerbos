import shutil
from pathlib import Path

import pytest

from app import policy_store
from app.config import settings


def test_playground_requires_a_session_and_demo_mode(client, sign_in, monkeypatch):
    assert client.get("/api/playground/catalog").status_code == 401
    sign_in("maya")
    assert client.get("/api/playground/catalog").status_code == 200
    monkeypatch.setattr(settings(), "demo_mode", False)
    assert client.get("/api/playground/catalog").status_code == 404
    assert client.get("/api/policies").status_code == 404


def test_catalog_lists_personas_kinds_actions_and_scenarios(client, sign_in):
    sign_in("maya")
    catalog = client.get("/api/playground/catalog").json()
    assert {p["id"] for p in catalog["personas"]} >= {"maya", "alex", "sam", "avery"}
    kinds = {k["kind"]: k for k in catalog["kinds"]}
    assert set(kinds["asset"]["actions"]) >= {"view", "edit", "delete", "use"}
    assert set(kinds["model"]["actions"]) == {"list", "invoke"}
    assert kinds["mcp_tool"]["actions"] == ["call"]
    assert "atlas" in {r["id"] for r in kinds["asset"]["resources"]}
    assert len(catalog["scenarios"]) >= 8
    assert {k["owner"] for k in catalog["demo_keys"]} == {"alex", "sam", "riley"}


def test_what_if_overrides_change_the_decision_and_explain_it(client, sign_in):
    sign_in("maya")
    body = {
        "principal": {"persona_id": "alex"},
        "kind": "asset",
        "resource_ids": ["atlas"],
        "actions": ["delete"],
    }
    before = client.post("/api/playground/check", json=body).json()["results"][0]
    assert before["decisions"]["delete"]["effect"] == "deny"
    body["principal"]["roles"] = ["developer_admin"]
    body["principal"]["admin_team_ids"] = ["platform"]
    after = client.post("/api/playground/check", json=body).json()["results"][0]
    assert after["decisions"]["delete"] == {
        "effect": "allow",
        "policy": "resource.asset.vdefault",
        "rule": "team-admin-deletes-team-asset",
        "reason": "Developer admins may delete assets of the teams they administer.",
    }


@pytest.mark.parametrize(
    "change",
    [
        {"principal": {"persona_id": "alex", "roles": ["superuser"]}},
        {"principal": {"persona_id": "alex", "team_ids": ["nowhere"]}},
        {"resource_overrides": {"not_an_attribute": "x"}},
        {"resource_overrides": {"status": {"nested": True}}},
        {"kind": "secrets"},
    ],
)
def test_overrides_are_validated(client, sign_in, change):
    sign_in("maya")
    body = {"principal": {"persona_id": "alex"}, "kind": "asset", "resource_ids": ["atlas"]}
    body.update(change)
    assert client.post("/api/playground/check", json=body).status_code == 422


def test_policies_can_be_listed_and_read_with_a_diff(client, sign_in):
    sign_in("maya")
    policies = {p["id"]: p for p in client.get("/api/policies").json()}
    assert set(policies) >= {"asset", "approval", "model"}
    assert not any(p["modified"] for p in policies.values())
    document = client.get("/api/policies/model").json()
    assert "premium_teams" in document["yaml"] and document["diff"] == ""
    assert client.get("/api/policies/model_test").status_code == 404


@pytest.fixture
def live_copy(tmp_path, monkeypatch):
    """A writable live directory, with the reload probe stubbed out."""
    if not shutil.which("cerbos"):
        pytest.skip("Cerbos CLI not installed")
    live = tmp_path / "live"
    shutil.copytree(settings().shipped_policies_dir, live)
    monkeypatch.setattr(settings(), "policies_dir", str(live))
    monkeypatch.setattr(policy_store, "publish_and_confirm", lambda: 0.0)
    return live


def test_policy_edit_is_compiled_tested_and_written(live_copy):
    document = policy_store.document("model")
    edited = document["yaml"].replace("['agents']", "['agents', 'platform']")
    result = policy_store.save("model", edited, document["sha"])
    assert result["compile"]["ok"]
    assert result["tests"]["failed"] >= 1
    assert {f["principal"] for f in result["tests"]["failures"]} == {"key_platform"}
    assert (live_copy / "model.yaml").read_text() == edited
    assert [p["id"] for p in policy_store.summary() if p["modified"]] == ["model"]


def test_broken_policy_is_rejected_and_not_written(live_copy):
    document = policy_store.document("model")
    broken = document["yaml"].replace("R.attr.tier == 'standard'", "R.attr.tier ==== x")
    with pytest.raises(policy_store.PolicyError) as error:
        policy_store.save("model", broken, document["sha"])
    assert error.value.status == 422
    assert error.value.payload["compile"]["errors"][0]["line"]
    assert (live_copy / "model.yaml").read_text() == document["yaml"]


def test_stale_edits_and_kind_changes_are_rejected(live_copy):
    document = policy_store.document("model")
    with pytest.raises(policy_store.PolicyError) as stale:
        policy_store.save("model", document["yaml"], "0" * 64)
    assert stale.value.status == 409
    renamed = document["yaml"].replace("resource: model", "resource: asset")
    with pytest.raises(policy_store.PolicyError) as kind:
        policy_store.save("model", renamed, document["sha"])
    assert kind.value.status == 422


def test_startup_sync_keeps_edits_and_reset_restores_shipped(live_copy):
    Path(live_copy, ".shipped.sha256").unlink(missing_ok=True)
    assert "installed" in policy_store.sync_on_startup()
    document = policy_store.document("model")
    policy_store.save("model", document["yaml"] + "\n# edited\n", document["sha"])
    assert "kept" in policy_store.sync_on_startup()
    assert policy_store.document("model")["modified"]
    policy_store.reset()
    assert not policy_store.document("model")["modified"]


def test_demo_reset_restores_the_sample_workspace(client, sign_in, db, monkeypatch):
    from sqlalchemy import select

    from app import demo, gateway
    from app.models import Approval, Asset

    deleted = []
    monkeypatch.setattr(
        gateway, "lite_request", lambda path, payload: deleted.append(payload) or {}
    )
    monkeypatch.setattr(demo, "revoke_upstream", lambda key_id: deleted.append(key_id))
    monkeypatch.setattr(policy_store, "reset", lambda: 0.0)
    sign_in("jordan")
    decision = {"decision": "approve", "note": "Approve before resetting"}
    assert client.post("/api/approvals/request-release/decision", json=decision).status_code == 200
    assert client.post("/api/demo/reset").status_code == 200
    db.expire_all()
    assert db.get(Approval, "request-release").status == "pending"
    assert db.get(Asset, "release-notes").status == "pending"
    assert len(db.scalars(select(Asset)).all()) > 5
    # The session survives: the same personas exist again.
    assert client.get("/api/state").status_code == 200


def test_a_principal_without_roles_is_explained_not_reported_as_an_outage(client, sign_in):
    sign_in("maya")
    body = {
        "principal": {"persona_id": "morgan", "roles": []},
        "kind": "asset",
        "resource_ids": ["atlas"],
    }
    response = client.post("/api/playground/check", json=body)
    assert response.status_code == 422
    assert "at least one role" in response.json()["detail"]
