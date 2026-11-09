"""The budget ledger LiteLLM's Cerbos guard uses: every route to LiteLLM is held to every cap.

These call the internal API exactly as infra/cerbos_guard.py does. A key sent straight to
LiteLLM, without the gateway, is the case that matters most.
"""

from datetime import timedelta

import pytest
from sqlalchemy import select

from app import ledger
from app.config import settings
from app.db import SessionLocal
from app.gateway import cipher, token_hash
from app.models import ApiKey, Budget, Event, Reservation, now

TOKEN = "sk-ledger-test-only"
LEVELS = ["organization", "department:technology", "asset:atlas", "team:platform", "key:direct"]


@pytest.fixture
def key(db):
    db.add(
        ApiKey(
            id="direct",
            name="Direct key",
            owner_id="alex",
            asset_id="atlas",
            department_id="technology",
            team_id="platform",
            token_hash=token_hash(TOKEN),
            encrypted_token=cipher().encrypt(TOKEN.encode()).decode(),
            prefix="sk-led…only",
            models=["governed-demo", "governed-premium"],
            rpm=100,
            tpm=100000,
            expires_at=now() + timedelta(days=1),
        )
    )
    db.add(
        Budget(
            id="key:direct",
            name="Direct",
            scope="key",
            department_id="technology",
            team_id="platform",
            limit_micros=1_000_000,
        )
    )
    db.commit()


def reserve_body(**changes):
    return {
        "key_id": "direct",
        "model": "governed-demo",
        "max_tokens": 10,
        "input_bytes": 5,
        "message_count": 1,
        "idempotency_key": "litellm-call-1",
        **changes,
    }


@pytest.fixture
def guard(client, ledger_token):
    client.headers["X-Ledger-Token"] = ledger_token
    return client


def test_ledger_requires_its_token(client, key, monkeypatch):
    assert client.post("/internal/ledger/reserve", json=reserve_body()).status_code == 401
    client.headers["X-Ledger-Token"] = "wrong"
    assert client.post("/internal/ledger/reserve", json=reserve_body()).status_code == 401
    # Without a configured token the ledger refuses everyone (fail closed).
    monkeypatch.setattr(settings(), "ledger_token", "")
    client.headers["X-Ledger-Token"] = ""
    assert client.post("/internal/ledger/reserve", json=reserve_body()).status_code == 401


def test_a_direct_call_is_reserved_and_settled_on_every_level(guard, key):
    with SessionLocal() as db:
        before = {b.id: b.spent_micros for b in db.scalars(select(Budget))}
    reserved = guard.post("/internal/ledger/reserve", json=reserve_body())
    assert reserved.status_code == 200, reserved.text
    body = reserved.json()
    assert sorted(body["budget_ids"]) == sorted(LEVELS)
    settled = guard.post(
        f"/internal/ledger/{body['reservation_id']}/settle",
        json={
            "answered_model": "governed-demo",
            "input_tokens": 20,
            "output_tokens": 3,
            "requested_model": "governed-demo",
            "max_tokens": 10,
        },
    )
    assert settled.json() == {"status": "settled", "actual_micros": 20 * 10 + 3 * 30}
    with SessionLocal() as db:
        for id in LEVELS:
            budget = db.get(Budget, id)
            assert budget.spent_micros == before[id] + 290 and budget.reserved_micros == 0
        reservation = db.get(Reservation, body["reservation_id"])
        assert reservation.entry == "direct"
        event = db.scalar(select(Event).where(Event.type == "ledger.settled"))
        assert event.detail["entry"] == "direct"
    # Settling twice charges once.
    again = guard.post(
        f"/internal/ledger/{body['reservation_id']}/settle",
        json={
            "answered_model": "governed-demo",
            "input_tokens": 20,
            "output_tokens": 3,
            "requested_model": "governed-demo",
            "max_tokens": 10,
        },
    )
    assert again.json()["status"] == "settled"
    with SessionLocal() as db:
        assert db.get(Budget, "key:direct").spent_micros == before["key:direct"] + 290


@pytest.mark.parametrize("level", LEVELS)
def test_a_direct_call_cannot_spend_past_any_cap(guard, key, level):
    with SessionLocal.begin() as db:
        budget = db.get(Budget, level)
        budget.limit_micros = budget.spent_micros
    refused = guard.post("/internal/ledger/reserve", json=reserve_body())
    assert refused.status_code == 429
    assert refused.json()["detail"]["scope"] == level.split(":")[0]
    with SessionLocal() as db:
        assert db.scalar(select(Reservation).where(Reservation.key_id == "direct")) is None
        event = db.scalar(select(Event).where(Event.type == "ledger.refused"))
        assert event.detail["entry"] == "direct" and event.detail["scope"] == level.split(":")[0]


def test_only_the_gateway_signature_marks_a_call_as_gateway(guard, key):
    forged = guard.post(
        "/internal/ledger/reserve", json=reserve_body(gateway_signature="0" * 64)
    ).json()
    signed = guard.post(
        "/internal/ledger/reserve",
        json=reserve_body(
            idempotency_key="from-gateway",
            gateway_signature=ledger.gateway_signature("direct", "from-gateway"),
        ),
    ).json()
    with SessionLocal() as db:
        assert db.get(Reservation, forged["reservation_id"]).entry == "direct"
        assert db.get(Reservation, signed["reservation_id"]).entry == "gateway"


def test_an_idempotency_key_reserves_once(guard, key):
    assert guard.post("/internal/ledger/reserve", json=reserve_body()).status_code == 200
    assert guard.post("/internal/ledger/reserve", json=reserve_body()).status_code == 409


@pytest.mark.parametrize(
    ("action", "status", "held"), [("release", "released", False), ("hold", "uncertain", True)]
)
def test_release_frees_and_hold_keeps_the_funds(guard, key, action, status, held):
    reserved = guard.post("/internal/ledger/reserve", json=reserve_body()).json()
    result = guard.post(
        f"/internal/ledger/{reserved['reservation_id']}/{action}", json={"reason": "test"}
    )
    assert result.json()["status"] == status
    with SessionLocal() as db:
        budget = db.get(Budget, "key:direct")
        assert budget.reserved_micros == (reserved["amount_micros"] if held else 0)
        assert budget.spent_micros == 0


def test_revoked_keys_and_unpriced_models_are_refused(guard, key):
    assert (
        guard.post("/internal/ledger/reserve", json=reserve_body(model="other")).status_code == 422
    )
    with SessionLocal.begin() as db:
        db.get(ApiKey, "direct").status = "revoked"
    assert guard.post("/internal/ledger/reserve", json=reserve_body()).status_code == 401
