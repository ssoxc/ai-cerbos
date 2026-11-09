"""The budget ledger: reserve before every model call, settle after it.

LiteLLM's Cerbos guard (infra/cerbos_guard.py) calls these endpoints for every model call,
however the call reached LiteLLM. Budgets therefore hold for calls that skip the
governed gateway: a key holder who calls LiteLLM directly is still checked against the
key, agent, team, department and organization caps. The gateway adds idempotency and
its own Cerbos check, but it no longer owns the money.

Flow, inside LiteLLM, after Cerbos has decided and its obligations are applied:
  reserve  the maximum possible cost of the final request, on every level, or refuse
  settle   the actual cost of the model that answered, from the provider's usage
  release  nothing reached a provider (for example another LiteLLM check refused it)
  hold     the provider outcome is unknown: keep the funds for reconciliation

The endpoints live under /internal, which the web server never proxies, and require the
shared ledger token. Without a configured token every call is refused (fail closed).
"""

import hashlib
import hmac
import logging
from datetime import timedelta
from typing import Literal

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from .config import settings
from .db import SessionLocal
from .events import bus
from .models import ApiKey, Asset, Budget, Reservation, User, now
from .schemas import StrictModel

logger = logging.getLogger(__name__)

# Micro-USD per token. Mirrors infra/litellm.yaml; premium costs five times as much.
PRICING = {
    "governed-demo": {"input": 10, "output": 30},
    "governed-premium": {"input": 50, "output": 150},
}
CONTEXT_LIMIT = 16_000
Entry = Literal["gateway", "direct"]


class LedgerRefusal(Exception):
    """A definitive refusal before any provider call: nothing is reserved or charged."""

    def __init__(self, status: int, reason: str, scope: str = ""):
        super().__init__(reason)
        self.status, self.reason, self.scope = status, reason, scope


def lock_mutation(db):
    # Global first, for every monetary/mutable authorization operation. This favors
    # correctness over throughput in the POC and avoids lock-order deadlocks.
    budget = db.scalar(select(Budget).where(Budget.id == "organization").with_for_update())
    if not budget:
        raise HTTPException(503, "Organization budget is not configured")
    return budget


def estimate_input_tokens(input_bytes: int, message_count: int) -> int:
    # Byte-based metering: never fewer tokens than the provider counts for these models.
    return input_bytes + 16 * message_count + 32


def maximum_cost(model: str, input_tokens: int, max_tokens: int) -> int:
    price = PRICING.get(model)
    if price is None:
        raise LedgerRefusal(422, "This model has no configured price")
    if input_tokens > CONTEXT_LIMIT:
        raise LedgerRefusal(422, "Input exceeds the supported context limit")
    return input_tokens * price["input"] + max_tokens * price["output"]


def actual_cost(model, input_used, output_used):
    price = PRICING[model]
    return input_used * price["input"] + output_used * price["output"]


def gateway_signature(key_id: str, idempotency_key: str) -> str:
    """Proves a call came through the gateway. Only the gateway and ledger hold the token."""
    message = f"{key_id}:{idempotency_key}".encode()
    return hmac.new(settings().ledger_token.encode(), message, hashlib.sha256).hexdigest()


def budget_ids(key: ApiKey) -> list[str]:
    ids = ["organization", f"department:{key.department_id}", f"asset:{key.asset_id}"]
    if key.team_id:
        ids.append(f"team:{key.team_id}")
    return [*ids, f"key:{key.id}"]


def _refused(key: ApiKey, refusal: LedgerRefusal, entry: str, model: str):
    """Record a budget or rate refusal; the refused transaction itself rolls back."""
    with SessionLocal.begin() as db:
        bus.emit(
            db,
            "ledger.refused",
            key.owner_id,
            key.id,
            key.department_id,
            key.team_id,
            scope=refusal.scope,
            reason=refusal.reason,
            entry=entry,
            model=model,
        )


def reserve(
    *,
    key_id: str,
    model: str,
    max_tokens: int,
    input_tokens: int,
    idempotency_key: str,
    entry: Entry,
    fingerprint: str = "",
    data_classification: str = "internal",
) -> dict:
    amount = maximum_cost(model, input_tokens, max_tokens)
    token_count = input_tokens + max_tokens
    with SessionLocal() as db:
        lock_mutation(db)
        key = db.scalar(select(ApiKey).where(ApiKey.id == key_id).with_for_update())
        if not key or key.status != "active" or key.expires_at <= now():
            raise LedgerRefusal(401, "API key is invalid, expired, or revoked")
        owner, asset = db.get(User, key.owner_id), db.get(Asset, key.asset_id)
        if not owner or not owner.active or not asset or asset.status != "active":
            raise LedgerRefusal(403, "API key owner or agent is unavailable")
        if db.scalar(
            select(Reservation.id).where(
                Reservation.key_id == key.id, Reservation.idempotency_key == idempotency_key
            )
        ):
            raise LedgerRefusal(409, "This idempotency key was already used")
        count, tokens = db.execute(
            select(func.count(), func.coalesce(func.sum(Reservation.tokens), 0)).where(
                Reservation.key_id == key.id, Reservation.created_at >= now() - timedelta(minutes=1)
            )
        ).one()
        refusal = None
        if count >= key.rpm or tokens + token_count > key.tpm:
            refusal = LedgerRefusal(
                429, "API key rate limit reached; retry after the current minute", "rate"
            )
        ids = budget_ids(key)
        budgets = db.scalars(
            select(Budget).where(Budget.id.in_(ids)).order_by(Budget.id).with_for_update()
        ).all()
        if len(budgets) != len(ids):
            raise LedgerRefusal(503, "A required budget is missing; request blocked")
        for budget in sorted(budgets, key=lambda b: ids.index(b.id)):
            if refusal is None and (
                budget.spent_micros + budget.reserved_micros + amount > budget.limit_micros
            ):
                refusal = LedgerRefusal(
                    429,
                    f"{budget.scope.capitalize()} budget has insufficient unreserved funds",
                    budget.scope,
                )
        if refusal:
            db.rollback()
            _refused(key, refusal, entry, model)
            raise refusal
        for budget in budgets:
            budget.reserved_micros += amount
        reservation = Reservation(
            key_id=key.id,
            idempotency_key=idempotency_key,
            fingerprint=fingerprint,
            budget_ids=ids,
            amount_micros=amount,
            tokens=token_count,
            entry=entry,
            model=model,
        )
        db.add(reservation)
        try:
            db.flush()
        except IntegrityError:  # A concurrent call with the same idempotency key won.
            db.rollback()
            raise LedgerRefusal(409, "This idempotency key was already used") from None
        bus.emit(
            db,
            "budget.reserved",
            key.owner_id,
            reservation.id,
            key.department_id,
            key.team_id,
            amount_micros=amount,
            entry=entry,
            model=model,
            data_classification=data_classification,
        )
        result = {"reservation_id": reservation.id, "amount_micros": amount, "budget_ids": ids}
        db.commit()
    return result


def _locked_reservation(db, reservation_id):
    lock_mutation(db)
    reservation = db.scalar(
        select(Reservation).where(Reservation.id == reservation_id).with_for_update()
    )
    if not reservation:
        raise HTTPException(404, "Unknown reservation")
    key = db.get(ApiKey, reservation.key_id)
    budgets = db.scalars(
        select(Budget)
        .where(Budget.id.in_(reservation.budget_ids))
        .order_by(Budget.id)
        .with_for_update()
    ).all()
    return reservation, key, budgets


def settle(
    *,
    reservation_id: str,
    answered_model: str,
    input_tokens: int,
    output_tokens: int,
    requested_model: str,
    max_tokens: int,
    data_classification: str,
    obligations: dict,
    response: dict | None = None,
) -> dict:
    """Charge what the answering model actually cost. Settling twice changes nothing."""
    with SessionLocal.begin() as db:
        reservation, key, budgets = _locked_reservation(db, reservation_id)
        if reservation.status != "reserved":
            return {"status": reservation.status, "actual_micros": reservation.actual_micros}
        if answered_model not in PRICING or min(input_tokens, output_tokens) < 0:
            _hold(db, reservation, key, "The provider reported an unpriced model or bad usage")
            return {"status": "uncertain", "actual_micros": None}
        actual = actual_cost(answered_model, input_tokens, output_tokens)
        for budget in budgets:
            budget.reserved_micros -= reservation.amount_micros
            budget.spent_micros += actual
        reservation.status, reservation.actual_micros = "settled", actual
        reservation.response = response
        detail = {
            "cost_micros": actual,
            "model": requested_model,
            "answered_model": answered_model,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "max_tokens": max_tokens,
            "data_classification": data_classification,
            "obligations": obligations,
            "entry": reservation.entry,
        }
        if actual > reservation.amount_micros:
            # Charged anyway: the provider was paid. Flag it, because the estimate was wrong.
            detail["overrun_micros"] = actual - reservation.amount_micros
        bus.emit(
            db,
            "ledger.settled",
            key.owner_id,
            reservation.id,
            key.department_id,
            key.team_id,
            **detail,
        )
        return {"status": "settled", "actual_micros": actual}


def release(*, reservation_id: str, reason: str) -> dict:
    """No provider was contacted, so nothing can have been charged."""
    with SessionLocal.begin() as db:
        reservation, key, budgets = _locked_reservation(db, reservation_id)
        if reservation.status != "reserved":
            return {"status": reservation.status}
        for budget in budgets:
            budget.reserved_micros -= reservation.amount_micros
        reservation.status, reservation.actual_micros = "released", 0
        bus.emit(
            db,
            "ledger.released",
            key.owner_id,
            reservation.id,
            key.department_id,
            key.team_id,
            reason=reason,
            entry=reservation.entry,
            model=reservation.model,
        )
        return {"status": "released"}


def _hold(db, reservation, key, reason):
    reservation.status = "uncertain"
    bus.emit(
        db,
        "ledger.uncertain",
        key.owner_id,
        reservation.id,
        key.department_id,
        key.team_id,
        reserved_micros=reservation.amount_micros,
        reason=reason,
        entry=reservation.entry,
        model=reservation.model,
    )


def hold(*, reservation_id: str, reason: str) -> dict:
    """The provider outcome is unknown: keep the funds and never retry automatically."""
    with SessionLocal.begin() as db:
        reservation, key, _ = _locked_reservation(db, reservation_id)
        if reservation.status == "reserved":
            _hold(db, reservation, key, reason)
        return {"status": reservation.status}


# --- Internal API for LiteLLM's Cerbos guard ------------------------------------------------

router = APIRouter(prefix="/internal/ledger", include_in_schema=False)


def ledger_caller(x_ledger_token: str = Header(default="")):
    expected = settings().ledger_token
    if not expected or not hmac.compare_digest(x_ledger_token.encode(), expected.encode()):
        raise HTTPException(401, "Ledger token required")


class ReserveRequest(StrictModel):
    key_id: str = Field(max_length=64)
    model: str = Field(max_length=100)
    max_tokens: int = Field(ge=1, le=100_000)
    input_bytes: int = Field(ge=0, le=10_000_000)
    message_count: int = Field(ge=0, le=10_000)
    idempotency_key: str = Field(min_length=1, max_length=100)
    # Set by the gateway; proves the call came through it. Absent for direct calls.
    gateway_signature: str = Field(default="", max_length=64)
    fingerprint: str = Field(default="", max_length=64)
    data_classification: str = Field(default="internal", max_length=20)


class SettleRequest(StrictModel):
    answered_model: str = Field(max_length=100)
    input_tokens: int
    output_tokens: int
    requested_model: str = Field(max_length=100)
    max_tokens: int
    data_classification: str = Field(default="internal", max_length=20)
    obligations: dict = Field(default_factory=dict)
    response: dict | None = None


class ReasonRequest(StrictModel):
    reason: str = Field(default="", max_length=300)


@router.post("/reserve", dependencies=[Depends(ledger_caller)])
def reserve_endpoint(body: ReserveRequest):
    signed = body.gateway_signature and hmac.compare_digest(
        body.gateway_signature, gateway_signature(body.key_id, body.idempotency_key)
    )
    try:
        return reserve(
            key_id=body.key_id,
            model=body.model,
            max_tokens=body.max_tokens,
            input_tokens=estimate_input_tokens(body.input_bytes, body.message_count),
            idempotency_key=body.idempotency_key,
            entry="gateway" if signed else "direct",
            fingerprint=body.fingerprint if signed else "",
            data_classification=body.data_classification,
        )
    except LedgerRefusal as refusal:
        raise HTTPException(
            refusal.status, {"reason": refusal.reason, "scope": refusal.scope}
        ) from None


@router.post("/{reservation_id}/settle", dependencies=[Depends(ledger_caller)])
def settle_endpoint(reservation_id: str, body: SettleRequest):
    return settle(reservation_id=reservation_id, **body.model_dump())


@router.post("/{reservation_id}/release", dependencies=[Depends(ledger_caller)])
def release_endpoint(reservation_id: str, body: ReasonRequest):
    return release(reservation_id=reservation_id, reason=body.reason)


@router.post("/{reservation_id}/hold", dependencies=[Depends(ledger_caller)])
def hold_endpoint(reservation_id: str, body: ReasonRequest):
    return hold(reservation_id=reservation_id, reason=body.reason)
