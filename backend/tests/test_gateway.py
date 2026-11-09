import json
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import httpx
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import gateway
from app.config import settings
from app.db import SessionLocal
from app.gateway import cipher, complete, maximum_cost, token_hash
from app.main import app
from app.models import ApiKey, Budget, Event, Reservation, now
from app.schemas import Completion

TOKEN = "sk-test-only-credential-never-valid-at-litellm"
BODY = Completion(
    model="governed-demo", messages=[{"role": "user", "content": "Hello"}], max_tokens=10
)
RESULT = {
    "choices": [{"message": {"role": "assistant", "content": "Hello"}}],
    "usage": {"prompt_tokens": 53, "completion_tokens": 1, "total_tokens": 54},
}


def litellm_error(status, message):
    request = httpx.Request("POST", "http://litellm:4000/v1/chat/completions")
    response = httpx.Response(status, json={"error": {"message": message}}, request=request)
    return httpx.HTTPStatusError("rejected", request=request, response=response)


GUARD_DENIAL = (
    '{"marker": "cerbos_guard", "decision": "deny", "rule": "premium-reserved-for-teams",'
    ' "reason": "Premium models are reserved for keys of the Agents & Automation team."}'
)


class FakeLiteLLM:
    """Stands in for LiteLLM and its Cerbos guard (infra/cerbos_guard.py) in forward_completion.

    Like the guard it reserves through the real internal ledger API, then answers and
    settles, or fails and releases (a 4xx) or holds (anything else). `deny` refuses before
    any reservation, as a Cerbos denial does.
    """

    def __init__(self, result=RESULT, headers=None, deny=None, error=None, wait=None):
        self.result, self.headers = result, headers or {}
        self.deny, self.error, self.wait = deny, error, wait
        self.provider_calls = 0
        self.api = TestClient(app, headers={"X-Ledger-Token": settings().ledger_token})

    def reserve(self, token, body, metadata):
        with SessionLocal() as db:
            key = db.scalar(select(ApiKey).where(ApiKey.token_hash == token_hash(token)))
        final_model = self.headers.get("x-litellm-model-group") or body.model  # After obligations.
        reserved = self.api.post(
            "/internal/ledger/reserve",
            json={
                "key_id": key.id,
                "model": final_model,
                "max_tokens": body.max_tokens,
                "input_bytes": sum(len(m.content.encode()) for m in body.messages),
                "message_count": len(body.messages),
                "idempotency_key": metadata.get("idempotency_key") or str(uuid.uuid4()),
                "gateway_signature": metadata.get("gateway_signature", ""),
                "fingerprint": metadata.get("fingerprint", ""),
                "data_classification": body.data_classification,
            },
        )
        if reserved.status_code != 200:
            detail = reserved.json()["detail"]
            message = {"marker": "cerbos_guard", "kind": "budget", **detail}
            raise litellm_error(reserved.status_code, json.dumps(message))
        return reserved.json(), final_model

    def settle(self, reservation, final_model, body):
        usage = self.result["usage"]
        settled = self.api.post(
            f"/internal/ledger/{reservation}/settle",
            json={
                "answered_model": final_model,
                "input_tokens": usage["prompt_tokens"],
                "output_tokens": usage["completion_tokens"],
                "requested_model": body.model,
                "max_tokens": body.max_tokens,
                "data_classification": body.data_classification,
                "obligations": json.loads(self.headers.get("x-cerbos-obligations", "{}")),
            },
        )
        assert settled.status_code == 200, settled.text

    def __call__(self, token, body, metadata=None):
        if self.deny:
            raise self.deny
        reserved, final_model = self.reserve(token, body, metadata or {})
        reservation = reserved["reservation_id"]
        if self.wait:
            self.wait()
        if self.error:
            status = getattr(getattr(self.error, "response", None), "status_code", None)
            action = "release" if status and 400 <= status < 500 else "hold"
            self.api.post(f"/internal/ledger/{reservation}/{action}", json={"reason": "test"})
            raise self.error
        self.provider_calls += 1
        self.settle(reservation, final_model, body)
        return self.result, self.headers

    def stream(self, token, body, metadata=None):
        """Like open_stream: refusals raise before any byte; settles before the stream ends."""
        if self.deny:
            raise self.deny
        reserved, final_model = self.reserve(token, body, metadata or {})
        reservation = reserved["reservation_id"]
        headers = {
            **self.headers,
            "x-ai-spine-reservation": reservation,
            "x-ai-spine-reserved-micros": str(reserved["amount_micros"]),
        }

        def chunks():
            finished = False
            try:
                yield b'data: {"choices": [{"delta": {"content": "Hello"}}]}\n\n'
                self.provider_calls += 1
                self.settle(reservation, final_model, body)
                yield b"data: [DONE]\n\n"
                finished = True
            finally:
                if not finished:
                    self.api.post(f"/internal/ledger/{reservation}/hold", json={"reason": "test"})

        return headers, chunks()


def use_litellm(monkeypatch, **kwargs) -> FakeLiteLLM:
    fake = FakeLiteLLM(**kwargs)
    monkeypatch.setattr(gateway, "forward_completion", fake)
    monkeypatch.setattr(gateway, "open_stream", fake.stream)
    return fake


def reservation_for(idempotency_key):
    with SessionLocal() as db:
        return db.scalar(select(Reservation).where(Reservation.idempotency_key == idempotency_key))


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
    litellm = use_litellm(monkeypatch)
    with SessionLocal() as db:
        before = {b.id: b.spent_micros for b in db.scalars(select(Budget))}
    assert complete(TOKEN, BODY, "same-request") == RESULT
    assert complete(TOKEN, BODY, "same-request") == RESULT
    assert litellm.provider_calls == 1
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
    assert reservation_for("same-request").entry == "gateway"


def test_concurrent_requests_cannot_spend_the_same_balance(key, monkeypatch):
    entered, release = threading.Event(), threading.Event()
    amount, _ = maximum_cost(BODY)
    with SessionLocal.begin() as db:
        db.get(Budget, "key:test-key").limit_micros = amount

    def slow():
        entered.set()
        assert release.wait(10)

    use_litellm(monkeypatch, wait=slow)
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
    litellm = use_litellm(monkeypatch)
    with SessionLocal.begin() as db:
        budget = db.get(Budget, scope)
        budget.limit_micros = budget.spent_micros
    trace = []
    with pytest.raises(HTTPException) as error:
        complete(TOKEN, BODY, scope, trace)
    assert error.value.status_code == 429 and litellm.provider_calls == 0
    assert "insufficient unreserved funds" in error.value.detail
    assert trace[-1]["name"] == gateway.BUDGET_STEP and trace[-1]["status"] == "deny"


def test_uncertain_provider_outcome_retains_funds_and_never_retries(key, monkeypatch):
    use_litellm(monkeypatch, error=httpx.ReadTimeout("Uncertain provider outcome"))
    with pytest.raises(HTTPException) as error:
        complete(TOKEN, BODY, "timeout")
    assert error.value.status_code == 502
    assert reservation_for("timeout").status == "uncertain"
    with SessionLocal() as db:
        assert db.get(Budget, "key:test-key").reserved_micros == maximum_cost(BODY)[0]
    with pytest.raises(HTTPException) as error:
        complete(TOKEN, BODY, "timeout")
    assert error.value.status_code == 409


@pytest.mark.parametrize("change", ["expired", "revoked", "rpm", "tpm"])
def test_expiry_revocation_and_rate_limits(key, monkeypatch, change):
    use_litellm(monkeypatch)
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


def test_unknown_models_are_rejected(client, key):
    headers = {"Authorization": f"Bearer {TOKEN}", "Idempotency-Key": "bad-model"}
    assert (
        client.post(
            "/v1/chat/completions",
            headers=headers,
            json={**BODY.model_dump(), "model": "unapproved"},
        ).status_code
        == 422
    )


STREAMED = {**BODY.model_dump(), "stream": True}


def test_a_streamed_answer_is_relayed_and_billed_on_every_level(client, key, monkeypatch):
    litellm = use_litellm(monkeypatch)
    with SessionLocal() as db:
        before = {b.id: b.spent_micros for b in db.scalars(select(Budget))}
    headers = {"Authorization": f"Bearer {TOKEN}", "Idempotency-Key": "streamed"}
    with client.stream("POST", "/v1/chat/completions", headers=headers, json=STREAMED) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        assert response.headers["x-ai-spine-reserved-micros"] == str(maximum_cost(BODY)[0])
        body = b"".join(response.iter_bytes())
    assert b"Hello" in body and body.endswith(b"data: [DONE]\n\n")
    assert litellm.provider_calls == 1
    reservation = reservation_for("streamed")
    assert reservation.status == "settled" and reservation.entry == "gateway"
    assert reservation.response is None  # Streams are not stored, so never replayed.
    with SessionLocal() as db:
        for id in ["organization", "department:technology", "team:platform", "asset:atlas"]:
            assert db.get(Budget, id).spent_micros == before[id] + 560
    # The same Idempotency-Key cannot start a second stream.
    again = client.post("/v1/chat/completions", headers=headers, json=STREAMED)
    assert again.status_code == 409 and "not replayed" in again.json()["detail"]


def test_a_streamed_request_over_budget_is_refused_before_any_byte(client, key, monkeypatch):
    use_litellm(monkeypatch)
    with SessionLocal.begin() as db:
        budget = db.get(Budget, "team:platform")
        budget.limit_micros = budget.spent_micros
    headers = {"Authorization": f"Bearer {TOKEN}", "Idempotency-Key": "streamed-over"}
    response = client.post("/v1/chat/completions", headers=headers, json=STREAMED)
    assert response.status_code == 429
    assert "Team budget" in response.json()["detail"]


def test_a_stream_the_client_abandons_keeps_its_funds_held(key, monkeypatch):
    use_litellm(monkeypatch)
    body = BODY.model_copy(update={"stream": True})
    _, chunks, _ = gateway.stream_completion(TOKEN, body, "abandoned")
    next(chunks)
    chunks.close()  # The client disconnected after the first chunk.
    assert reservation_for("abandoned").status == "uncertain"
    with SessionLocal() as db:
        assert db.get(Budget, "key:test-key").reserved_micros == maximum_cost(BODY)[0]


def test_idempotency_key_cannot_be_reused_for_different_content(key, monkeypatch):
    use_litellm(monkeypatch)
    complete(TOKEN, BODY, "unique")
    different = BODY.model_copy(update={"max_tokens": 20})
    with pytest.raises(HTTPException) as error:
        complete(TOKEN, different, "unique")
    assert error.value.status_code == 409


def test_cerbos_guard_rejection_reserves_nothing(key, monkeypatch):
    use_litellm(monkeypatch, deny=litellm_error(403, GUARD_DENIAL))
    trace = []
    with pytest.raises(HTTPException) as error:
        complete(TOKEN, BODY, "guard-denied", trace)
    assert error.value.status_code == 403
    assert "reserved for keys of the Agents" in error.value.detail
    assert reservation_for("guard-denied") is None
    with SessionLocal() as db:
        assert db.get(Budget, "key:test-key").reserved_micros == 0
        assert db.get(Budget, "key:test-key").spent_micros == 0
    denied = [s for s in trace if s["status"] == "deny"]
    assert denied and denied[0]["rule"] == "premium-reserved-for-teams"


@pytest.mark.parametrize(
    ("error", "status"),
    [
        # The provider refused without doing the work: the guard releases.
        (litellm_error(403, "Provider refused the request"), "released"),
        (litellm_error(403, '{"marker": "someone_else"}'), "released"),
        # Unknown outcomes: the guard holds the funds for reconciliation.
        (litellm_error(500, GUARD_DENIAL), "uncertain"),
        (httpx.ReadTimeout("Uncertain provider outcome"), "uncertain"),
    ],
)
def test_failures_after_reservation_release_or_hold(key, monkeypatch, error, status):
    use_litellm(monkeypatch, error=error)
    with pytest.raises(HTTPException) as raised:
        complete(TOKEN, BODY, "not-the-guard")
    assert raised.value.status_code == 502
    assert reservation_for("not-the-guard").status == status
    with SessionLocal() as db:
        held = db.get(Budget, "key:test-key").reserved_micros
    assert held == (maximum_cost(BODY)[0] if status == "uncertain" else 0)


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
    use_litellm(monkeypatch, headers=headers)
    premium = BODY.model_copy(update={"model": "governed-premium"})
    with SessionLocal() as db:
        before = db.get(Budget, "key:test-key").spent_micros
    trace = []
    complete(TOKEN, premium, "downgraded", trace)
    with SessionLocal() as db:
        spent = db.get(Budget, "key:test-key").spent_micros - before
    assert spent == gateway.actual_cost("governed-demo", 53, 1)
    step = next(s for s in trace if "Cerbos inside LiteLLM" in s["name"])
    assert step["rule"] == "premium-downgraded-for-other-teams"
    assert step["obligations"] == {"model": "governed-demo"}
    # The ledger keeps what was asked for and what answered, for metrics.
    with SessionLocal() as db:
        event = db.scalars(
            select(Event).where(Event.type == "ledger.settled").order_by(Event.created_at.desc())
        ).first()
    assert event.detail["model"] == "governed-premium"
    assert event.detail["answered_model"] == "governed-demo"
    assert (event.detail["input_tokens"], event.detail["output_tokens"]) == (53, 1)
    assert event.detail["obligations"] == {"model": "governed-demo"}
    assert event.detail["entry"] == "gateway"


def test_classification_travels_to_litellm_as_metadata():
    confidential = BODY.model_copy(update={"data_classification": "confidential"})
    body = confidential.litellm_body()
    assert body["metadata"] == {"data_classification": "confidential"}
    assert "data_classification" not in body
