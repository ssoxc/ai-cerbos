import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import httpx
import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app import gateway
from app.db import SessionLocal
from app.gateway import cipher, complete, maximum_cost, token_hash
from app.models import ApiKey, Budget, Reservation, now
from app.schemas import Completion

TOKEN = "sk-test-only-credential-never-valid-at-litellm"
BODY = Completion(
    model="governed-demo", messages=[{"role": "user", "content": "Hello"}], max_tokens=10
)
RESULT = {
    "choices": [{"message": {"role": "assistant", "content": "Hello"}}],
    "usage": {"prompt_tokens": 53, "completion_tokens": 1, "total_tokens": 54},
}
# forward_completion returns the JSON body and LiteLLM's response headers.
RESPONSE = (RESULT, {})


@pytest.fixture
def key(db):
    key = ApiKey(
        id="test-key",
        name="Test key",
        owner_id="alex",
        asset_id="atlas",
        department_id="technology",
        team_id="platform",
        token_hash=token_hash(TOKEN),
        encrypted_token=cipher().encrypt(TOKEN.encode()).decode(),
        prefix="sk-test…only",
        models=["governed-demo", "governed-premium"],
        rpm=100,
        tpm=100000,
        expires_at=now() + timedelta(days=1),
    )
    db.add(key)
    db.add(
        Budget(
            id="key:test-key",
            name="Test",
            scope="key",
            department_id="technology",
            team_id="platform",
            limit_micros=1000000,
        )
    )
    db.commit()
    return key


def test_litellm_key_workflow_is_owner_only_and_once(client, sign_in, monkeypatch):
    monkeypatch.setattr(gateway, "lite_request", lambda path, payload: {"key": TOKEN})
    sign_in("sam")
    response = client.post(
        "/api/approvals/request-atlas-key/decision",
        json={
            "decision": "approve",
            "note": "Approved with reduced cap",
            "budget": "20",
            "rpm": 10,
            "tpm": 10000,
        },
    )
    assert response.status_code == 200, response.text
    key = client.get("/api/state").json()["keys"][0]
    assert "encrypted_token" not in key and "token_hash" not in key
    assert client.post(f"/api/keys/{key['id']}/claim").status_code == 403
    sign_in("alex")
    assert client.post(f"/api/keys/{key['id']}/claim").status_code == 200
    assert client.post(f"/api/keys/{key['id']}/claim").status_code == 409


def test_key_approver_cannot_increase_requested_limits(client, sign_in):
    sign_in("sam")
    assert (
        client.post(
            "/api/approvals/request-atlas-key/decision",
            json={"decision": "approve", "note": "Try to increase requested cap", "budget": "500"},
        ).status_code
        == 422
    )


def test_cost_is_settled_across_all_budgets_and_retry_is_idempotent(key, monkeypatch):
    calls = []
    monkeypatch.setattr(gateway, "forward_completion", lambda *args: calls.append(1) or RESPONSE)
    with SessionLocal() as db:
        before = {b.id: b.spent_micros for b in db.scalars(select(Budget))}
    assert complete(TOKEN, BODY, "same-request") == RESULT
    assert complete(TOKEN, BODY, "same-request") == RESULT
    assert len(calls) == 1
    with SessionLocal() as db:
        for id in [
            "organization",
            "department:technology",
            "team:platform",
            "asset:atlas",
            "key:test-key",
        ]:
            budget = db.get(Budget, id)
            assert budget.spent_micros == before[id] + 560
            assert budget.reserved_micros == 0


def test_concurrent_requests_cannot_spend_the_same_balance(key, monkeypatch):
    entered, release = threading.Event(), threading.Event()
    amount, _ = maximum_cost(BODY)
    with SessionLocal.begin() as db:
        db.get(Budget, "key:test-key").limit_micros = amount

    def slow(*args):
        entered.set()
        assert release.wait(10)
        return RESPONSE

    monkeypatch.setattr(gateway, "forward_completion", slow)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(complete, TOKEN, BODY, "first")
        assert entered.wait(10)
        try:
            with pytest.raises(HTTPException) as error:
                complete(TOKEN, BODY, "second")
            assert error.value.status_code == 429
        finally:
            release.set()
        assert first.result() == RESULT
    with SessionLocal() as db:
        budget = db.get(Budget, "key:test-key")
        assert budget.spent_micros + budget.reserved_micros <= budget.limit_micros


@pytest.mark.parametrize(
    "scope",
    ["organization", "department:technology", "team:platform", "asset:atlas", "key:test-key"],
)
def test_every_budget_level_blocks_before_provider_call(key, monkeypatch, scope):
    called = []
    monkeypatch.setattr(gateway, "forward_completion", lambda *args: called.append(1) or RESPONSE)
    with SessionLocal.begin() as db:
        budget = db.get(Budget, scope)
        budget.limit_micros = budget.spent_micros
    with pytest.raises(HTTPException) as error:
        complete(TOKEN, BODY, scope)
    assert error.value.status_code == 429 and not called


def test_uncertain_provider_outcome_retains_funds_and_never_retries(key, monkeypatch):
    def timeout(*args):
        raise httpx.ReadTimeout("Uncertain provider outcome")

    monkeypatch.setattr(gateway, "forward_completion", timeout)
    with pytest.raises(HTTPException) as error:
        complete(TOKEN, BODY, "timeout")
    assert error.value.status_code == 502
    with SessionLocal() as db:
        reservation = db.scalar(select(Reservation).where(Reservation.idempotency_key == "timeout"))
        assert reservation.status == "uncertain"
        assert db.get(Budget, "key:test-key").reserved_micros == maximum_cost(BODY)[0]
    with pytest.raises(HTTPException) as error:
        complete(TOKEN, BODY, "timeout")
    assert error.value.status_code == 409


@pytest.mark.parametrize("change", ["expired", "revoked", "rpm", "tpm"])
def test_expiry_revocation_and_rate_limits(key, monkeypatch, change):
    monkeypatch.setattr(gateway, "forward_completion", lambda *args: RESPONSE)
    with SessionLocal.begin() as db:
        key = db.get(ApiKey, "test-key")
        if change == "expired":
            key.expires_at = now() - timedelta(seconds=1)
        if change == "revoked":
            key.status = "revoked"
        if change == "rpm":
            key.rpm = 0
        if change == "tpm":
            key.tpm = 1
    with pytest.raises(HTTPException) as error:
        complete(TOKEN, BODY, change)
    assert error.value.status_code == (401 if change in ("expired", "revoked") else 429)


def test_unknown_models_and_streaming_are_rejected(client, key):
    headers = {"Authorization": f"Bearer {TOKEN}", "Idempotency-Key": "bad-model"}
    assert (
        client.post(
            "/v1/chat/completions",
            headers=headers,
            json={**BODY.model_dump(), "model": "unapproved"},
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/v1/chat/completions", headers=headers, json={**BODY.model_dump(), "stream": True}
        ).status_code
        == 422
    )


def test_idempotency_key_cannot_be_reused_for_different_content(key, monkeypatch):
    monkeypatch.setattr(gateway, "forward_completion", lambda *args: RESPONSE)
    complete(TOKEN, BODY, "unique")
    different = BODY.model_copy(update={"max_tokens": 20})
    with pytest.raises(HTTPException) as error:
        complete(TOKEN, different, "unique")
    assert error.value.status_code == 409


def litellm_error(status, message):
    request = httpx.Request("POST", "http://litellm:4000/v1/chat/completions")
    response = httpx.Response(status, json={"error": {"message": message}}, request=request)
    return httpx.HTTPStatusError("rejected", request=request, response=response)


GUARD_DENIAL = (
    '{"marker": "cerbos_guard", "decision": "deny", "rule": "premium-reserved-for-teams",'
    ' "reason": "Premium models are reserved for keys of the Agents & Automation team."}'
)


def test_cerbos_guard_rejection_releases_the_reservation(key, monkeypatch):
    def rejected(*args):
        raise litellm_error(403, GUARD_DENIAL)

    monkeypatch.setattr(gateway, "forward_completion", rejected)
    trace = []
    with pytest.raises(HTTPException) as error:
        complete(TOKEN, BODY, "guard-denied", trace)
    assert error.value.status_code == 403
    assert "reserved for keys of the Agents" in error.value.detail
    with SessionLocal() as db:
        reservation = db.scalar(
            select(Reservation).where(Reservation.idempotency_key == "guard-denied")
        )
        assert reservation.status == "denied"
        assert db.get(Budget, "key:test-key").reserved_micros == 0
        assert db.get(Budget, "key:test-key").spent_micros == 0
    denied = [s for s in trace if s["status"] == "deny"]
    assert denied and denied[0]["rule"] == "premium-reserved-for-teams"


@pytest.mark.parametrize(
    "error",
    [
        litellm_error(403, "Provider refused the request"),
        litellm_error(403, '{"marker": "someone_else"}'),
        litellm_error(500, GUARD_DENIAL),
        httpx.ReadTimeout("Uncertain provider outcome"),
    ],
)
def test_other_failures_keep_funds_reserved(key, monkeypatch, error):
    def failed(*args):
        raise error

    monkeypatch.setattr(gateway, "forward_completion", failed)
    with pytest.raises(HTTPException) as raised:
        complete(TOKEN, BODY, "not-the-guard")
    assert raised.value.status_code == 502
    with SessionLocal() as db:
        reservation = db.scalar(
            select(Reservation).where(Reservation.idempotency_key == "not-the-guard")
        )
        assert reservation.status == "uncertain"
        assert db.get(Budget, "key:test-key").reserved_micros == maximum_cost(BODY)[0]


def test_premium_model_is_priced_higher():
    premium = BODY.model_copy(update={"model": "governed-premium"})
    assert maximum_cost(premium)[0] == 5 * maximum_cost(BODY)[0]


def test_downgraded_request_is_settled_at_the_answering_models_price(key, monkeypatch):
    # Cerbos inside LiteLLM downgraded premium to standard; LiteLLM reports the model group.
    headers = {
        "x-litellm-model-group": "governed-demo",
        "x-cerbos-decision": "allow",
        "x-cerbos-rule": "premium-downgraded-for-other-teams",
        "x-cerbos-reason": "Downgraded",
        "x-cerbos-obligations": '{"model": "governed-demo"}',
    }
    monkeypatch.setattr(gateway, "forward_completion", lambda *args: (RESULT, headers))
    premium = BODY.model_copy(update={"model": "governed-premium"})
    with SessionLocal() as db:
        before = db.get(Budget, "key:test-key").spent_micros
    trace = []
    complete(TOKEN, premium, "downgraded", trace)
    with SessionLocal() as db:
        spent = db.get(Budget, "key:test-key").spent_micros - before
    assert spent == gateway.actual_cost("governed-demo", 53, 1)
    step = next(s for s in trace if "inside LiteLLM" in s["name"])
    assert step["rule"] == "premium-downgraded-for-other-teams"
    assert step["obligations"] == {"model": "governed-demo"}


def test_classification_travels_to_litellm_as_metadata():
    confidential = BODY.model_copy(update={"data_classification": "confidential"})
    body = confidential.litellm_body()
    assert body["metadata"] == {"data_classification": "confidential"}
    assert "data_classification" not in body
