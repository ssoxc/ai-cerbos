import httpx
import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app import gateway
from app.models import ApiKey, Approval


def test_duplicate_display_names_have_independent_upstream_aliases(
    client, sign_in, monkeypatch, db
):
    issued = {}

    def generate(path, payload):
        assert path == "/key/generate"
        alias = payload["key_alias"]
        if alias in issued:
            raise HTTPException(422, "LiteLLM requires globally unique aliases")
        issued[alias] = payload
        return {"key": f"sk-test-{alias}"}

    monkeypatch.setattr(gateway, "lite_request", generate)
    sign_in("alex")
    for _ in range(2):
        result = client.post(
            "/api/key-requests",
            json={
                "asset_id": "atlas",
                "name": "Robin",
                "budget": "1",
                "rpm": 10,
                "tpm": 10000,
                "days": 1,
                "reason": "Duplicate project display names must be supported",
            },
        )
        assert result.status_code == 201, result.text
    requests = db.scalars(select(Approval).where(Approval.title == "Robin")).all()
    assert len(requests) == 2
    sign_in("sam")
    for request in requests:
        result = client.post(
            f"/api/approvals/{request.id}/decision",
            json={"decision": "approve", "note": "Approve independent project key"},
        )
        assert result.status_code == 200, result.text
    keys = db.scalars(select(ApiKey).where(ApiKey.name == "Robin")).all()
    assert len(keys) == len(issued) == 2
    assert len({k.token_hash for k in keys}) == 2
    for key in keys:
        payload = issued[f"ai-cerbos-{key.id}"]
        assert payload["metadata"]["display_name"] == "Robin"
        assert payload["metadata"]["key_id"] == key.id
        assert payload["max_budget"] == 1
        assert payload["models"] == ["governed-demo", "governed-premium"]
        # LiteLLM's Cerbos guard reads these as the key's principal attributes.
        assert payload["metadata"]["owner_id"] == "alex"
        assert payload["metadata"]["team_id"] == "platform"
        assert payload["metadata"]["asset_id"] == "atlas"


def test_failed_issuance_stays_pending_and_retry_uses_new_alias(client, sign_in, monkeypatch, db):
    attempts = []

    def generate(path, payload):
        attempts.append(payload["key_alias"])
        if len(attempts) == 1:
            # The upstream may have created a key before its response was lost.
            raise HTTPException(503, "Connection lost")
        return {"key": f"sk-test-{payload['key_alias']}"}

    monkeypatch.setattr(gateway, "lite_request", generate)
    sign_in("sam")
    body = {"decision": "approve", "note": "Retry after a failed issuance"}
    path = "/api/approvals/request-atlas-key/decision"
    assert client.post(path, json=body).status_code == 503
    assert db.get(Approval, "request-atlas-key").status == "pending"
    assert db.scalars(select(ApiKey)).all() == []
    assert client.post(path, json=body).status_code == 200
    db.expire_all()
    assert db.get(Approval, "request-atlas-key").status == "approved"
    assert len(db.scalars(select(ApiKey)).all()) == 1
    assert len(set(attempts)) == 2
    assert client.post(path, json=body).status_code == 403
    assert len(attempts) == 2


@pytest.mark.parametrize(
    "upstream_status,expected_status,message",
    [
        (400, 422, "rejected the requested key settings"),
        (401, 502, "rejected the gateway credentials"),
        (403, 502, "rejected the gateway credentials"),
        (409, 409, "key conflict"),
        (422, 422, "rejected the requested key settings"),
        (429, 503, "rate limiting"),
        (500, 503, "could not complete key generation"),
    ],
)
def test_litellm_rejection_is_not_misreported_as_connectivity_failure(
    monkeypatch, caplog, upstream_status, expected_status, message
):
    secret = "sk-sensitive-upstream-value"
    transport = httpx.MockTransport(
        lambda request: httpx.Response(upstream_status, json={"error": secret})
    )
    original_client = httpx.Client
    monkeypatch.setattr(
        gateway.httpx, "Client", lambda **kwargs: original_client(transport=transport, **kwargs)
    )
    with pytest.raises(HTTPException) as error:
        gateway.lite_request("/key/generate", {})
    assert error.value.status_code == expected_status
    assert message in error.value.detail
    assert "No approval has been completed" in error.value.detail
    assert secret not in error.value.detail + caplog.text
    assert f"status={upstream_status}" in caplog.text


def test_litellm_connection_failure_has_a_specific_error(monkeypatch):
    def disconnected(request):
        raise httpx.ConnectError("Connection refused", request=request)

    original_client = httpx.Client
    monkeypatch.setattr(
        gateway.httpx,
        "Client",
        lambda **kwargs: original_client(transport=httpx.MockTransport(disconnected), **kwargs),
    )
    with pytest.raises(HTTPException) as error:
        gateway.lite_request("/key/generate", {})
    assert error.value.status_code == 503
    assert "cannot be reached" in error.value.detail
