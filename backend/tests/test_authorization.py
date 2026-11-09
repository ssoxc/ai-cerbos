import httpx
import pytest

from app import policy
from app.models import Approval, Asset, Budget, User
from app.policy import approval_resource, asset_resource, permissions


@pytest.mark.parametrize(
    "actor,asset_id,action,expected",
    [
        ("maya", "atlas", "view", True),
        ("maya", "code-review", "view", False),
        ("maya", "atlas", "edit", False),
        ("maya", "release-notes", "edit", True),
        ("alex", "code-review", "edit", True),
        ("alex", "atlas", "delete", False),
        ("morgan", "atlas", "delete", True),
        ("morgan", "people-assistant", "delete", False),
        ("jordan", "people-assistant", "view", False),
        ("jordan", "atlas", "view", True),
        ("avery", "code-review", "view", True),
        ("avery", "atlas", "edit", False),
        ("avery", "atlas", "delete", False),
        ("riley", "atlas", "request_key", False),
        ("sam", "insights", "request_key", True),
    ],
)
def test_real_cerbos_asset_matrix(db, actor, asset_id, action, expected):
    result = permissions(db.get(User, actor), asset_resource(db.get(Asset, asset_id)), [action])
    assert result[action] is expected


def test_department_admin_isolation_in_api_and_reads(client, sign_in):
    sign_in("jordan")
    state = client.get("/api/state").json()
    assert {a["department_id"] for a in state["assets"]} == {"technology"}
    assert {a["department_id"] for a in state["approvals"]} == {"technology"}
    assert (
        client.patch(
            "/api/budgets/department:people",
            json={"amount": "7000", "reason": "Cross scope attempt"},
        ).status_code
        == 403
    )
    assert (
        client.post(
            "/api/approvals/request-people-budget/decision",
            json={"decision": "approve", "note": "Cross scope attempt"},
        ).status_code
        == 403
    )


def test_executive_cannot_mutate_assets_via_direct_api(client, sign_in):
    sign_in("avery")
    assert client.delete("/api/assets/atlas").status_code == 403
    assert (
        client.patch(
            "/api/assets/atlas",
            json={
                "name": "Changed asset",
                "description": "Should not be changed",
                "endpoint": "",
                "version": 1,
            },
        ).status_code
        == 403
    )
    assert (
        client.post(
            "/api/departments", json={"name": "Finance", "description": "Financial operations"}
        ).status_code
        == 201
    )


def test_self_approval_is_denied_by_cerbos(db):
    approval = db.get(Approval, "request-release")
    approval.requester_id = "jordan"
    assert not permissions(db.get(User, "jordan"), approval_resource(approval), ["approve"])[
        "approve"
    ]


def test_agents_reviewer_requires_role_and_team(db):
    approval = db.get(Approval, "request-atlas-key")
    user = db.get(User, "sam")
    assert permissions(user, approval_resource(approval), ["approve"])["approve"]
    user.team_ids = ["platform"]
    assert not permissions(user, approval_resource(approval), ["approve"])["approve"]


def test_personal_ownership_does_not_allow_team_deletion(client, sign_in):
    sign_in("maya")
    created = client.post(
        "/api/assets",
        json={
            "name": "Personal helper",
            "description": "A personal research helper",
            "kind": "agent",
            "department_id": "technology",
            "visibility": "private",
            "budget": "10",
        },
    )
    assert created.status_code == 201, created.text
    assert client.delete(f"/api/assets/{created.json()['id']}").status_code == 200
    assert client.delete("/api/assets/release-notes").status_code == 403


def test_authoritative_scope_cannot_be_spoofed(client, sign_in):
    sign_in("alex")
    body = {
        "name": "Unauthorized",
        "description": "Wrong department assignment",
        "kind": "agent",
        "department_id": "people",
        "team_id": "people-ops",
        "budget": "10",
    }
    assert client.post("/api/assets", json=body).status_code == 403
    body.update(department_id="technology", team_id="platform", owner_id="avery")
    assert client.post("/api/assets", json=body).status_code == 422


def test_revoked_delegation_blocks_pending_budget_approval(client, sign_in, db):
    db.get(Approval, "request-atlas-budget").status = "cancelled"
    db.commit()
    sign_in("alex")
    assert (
        client.post(
            "/api/assets/atlas/budget-requests",
            json={"amount": "1300", "reason": "Expand research usage"},
        ).status_code
        == 201
    )
    request = next(
        a
        for a in client.get("/api/state").json()["approvals"]
        if a["kind"] == "budget" and a["status"] == "pending"
    )
    sign_in("morgan")
    assert (
        client.put(
            "/api/teams/platform/delegations", json={"user_id": "alex", "grant": False}
        ).status_code
        == 200
    )
    sign_in("alex")
    asset = next(a for a in client.get("/api/state").json()["assets"] if a["id"] == "atlas")
    assert not asset["permissions"]["request_budget"]
    sign_in("jordan")
    assert (
        client.post(
            f"/api/approvals/{request['id']}/decision",
            json={"decision": "approve", "note": "Review after revocation"},
        ).status_code
        == 403
    )


def test_cost_center_cannot_change_global_budget(client, sign_in):
    sign_in("jordan")
    assert (
        client.patch(
            "/api/budgets/organization",
            json={"amount": "30000", "reason": "Increase organization cap"},
        ).status_code
        == 403
    )
    sign_in("quinn")
    assert (
        client.patch(
            "/api/budgets/organization",
            json={"amount": "30000", "reason": "Increase organization cap"},
        ).status_code
        == 200
    )


def test_review_is_atomic_and_cannot_be_replayed(client, sign_in, db):
    sign_in("jordan")
    payload = {"decision": "approve", "note": "Approved for research pilot"}
    assert (
        client.post("/api/approvals/request-atlas-budget/decision", json=payload).status_code == 200
    )
    assert (
        client.post("/api/approvals/request-atlas-budget/decision", json=payload).status_code == 403
    )
    db.expire_all()
    assert db.get(Budget, "asset:atlas").limit_micros == 1600000000


def test_financial_limits_cannot_drop_below_committed_spend(client, sign_in):
    sign_in("jordan")
    assert (
        client.patch(
            "/api/budgets/team:platform", json={"amount": "1", "reason": "Too low to cover spend"}
        ).status_code
        == 409
    )


def test_session_required_and_csrf_header_checked(client):
    assert client.get("/api/state").status_code == 401
    assert (
        client.post(
            "/api/session", headers={"X-Requested-With": ""}, json={"user_id": "avery"}
        ).status_code
        == 403
    )
    assert (
        client.post(
            "/api/session",
            headers={"Origin": "https://attacker.invalid"},
            json={"user_id": "avery"},
        ).status_code
        == 403
    )


def test_cerbos_failure_denies_access(client, sign_in, monkeypatch):
    sign_in("alex")

    class Unavailable:
        def __init__(self, *args, **kwargs):
            raise httpx.ConnectError("Unavailable")

    monkeypatch.setattr(policy.httpx, "Client", Unavailable)
    assert client.get("/api/state").status_code == 503


def test_private_assets_cannot_accidentally_grant_team_access(client, sign_in):
    sign_in("alex")
    body = {
        "name": "Private helper",
        "description": "Private research workspace",
        "kind": "agent",
        "department_id": "technology",
        "team_id": "platform",
        "visibility": "private",
        "budget": "10",
    }
    assert client.post("/api/assets", json=body).status_code == 422


def test_viewer_navigation_does_not_expose_key_management(client, sign_in):
    sign_in("maya")
    state = client.get("/api/state").json()
    assert not state["permissions"]["view_keys"]
    assert not state["permissions"]["view_budgets"]
    assert state["permissions"]["register_asset"]
