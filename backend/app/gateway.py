"""Only this gateway is exposed. LiteLLM and the provider have no published ports."""

import hashlib
import json
import logging
from datetime import timedelta

import httpx
from cryptography.fernet import Fernet
from fastapi import HTTPException
from sqlalchemy import func, select

from .config import settings
from .db import SessionLocal
from .events import bus
from .models import ApiKey, Asset, Budget, Reservation, User, now, uid
from .policy import asset_resource, explain, principal

# Micro-USD per token. Mirrors infra/litellm.yaml; premium costs five times as much.
PRICING = {
    "governed-demo": {"input": 10, "output": 30},
    "governed-premium": {"input": 50, "output": 150},
}
MODEL_TIERS = {"governed-demo": "standard", "governed-premium": "premium"}
MODELS = list(PRICING)
# MCP servers proxied by LiteLLM (infra/litellm.yaml).
MCP_SERVERS = ["knowledge"]
GUARD_MARKER = "cerbos_guard"
logger = logging.getLogger(__name__)


def cipher():
    return Fernet(settings().encryption_key.encode())


def token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


def lock_mutation(db):
    # Global first, for every monetary/mutable authorization operation. This favors
    # correctness over throughput in the POC and avoids lock-order deadlocks.
    budget = db.scalar(select(Budget).where(Budget.id == "organization").with_for_update())
    if not budget:
        raise HTTPException(503, "Organization budget is not configured")
    return budget


def lite_request(path, payload):
    try:
        with httpx.Client(timeout=30) as client:
            response = client.post(
                f"{settings().litellm_url}{path}",
                headers={"Authorization": f"Bearer {settings().litellm_master_key}"},
                json=payload,
            )
            response.raise_for_status()
            return response.json()
    except httpx.HTTPStatusError as error:
        status = error.response.status_code
        # Never expose upstream bodies: they may contain credentials or internal details.
        logger.warning("LiteLLM management request failed: path=%s status=%s", path, status)
        if status in (401, 403):
            code, detail = (
                502,
                "LiteLLM rejected the gateway credentials; check service configuration.",
            )
        elif status == 409:
            code, detail = 409, "LiteLLM reported a key conflict; retry the approval."
        elif status in (400, 422):
            code, detail = (
                422,
                "LiteLLM rejected the requested key settings; review the key limits.",
            )
        elif status == 429:
            code, detail = 503, "LiteLLM is rate limiting key management; retry shortly."
        else:
            code, detail = (
                503,
                "LiteLLM could not complete key generation; retry when it is healthy.",
            )
        raise HTTPException(code, f"{detail} No approval has been completed.") from None
    except httpx.RequestError:
        logger.warning("LiteLLM management connection failed: path=%s", path)
        raise HTTPException(
            503,
            "LiteLLM cannot be reached. No approval has been completed; retry when it is reachable.",
        ) from None
    except ValueError:
        logger.warning("LiteLLM management returned invalid JSON: path=%s", path)
        raise HTTPException(
            502, "LiteLLM returned an invalid response. No approval has been completed."
        ) from None


def upstream_alias(key_id):
    return f"ai-cerbos-{key_id}"


def revoke_upstream(key_id):
    """Best-effort deletion at LiteLLM after the local revocation has committed.

    Local status is authoritative and the gateway enforces it immediately; LiteLLM has
    no published port. This only prevents a stale virtual key lingering upstream.
    """
    try:
        lite_request("/key/delete", {"key_aliases": [upstream_alias(key_id)]})
    except HTTPException:
        logger.warning("LiteLLM key deletion deferred: key=%s", key_id)


def generate_upstream_key(*, name, owner, asset, amount, rpm, tpm, days, extra_metadata=None):
    """Create a LiteLLM virtual key and return the matching, not yet persisted, ApiKey row.

    The metadata is what LiteLLM's Cerbos guard uses as the key's principal attributes
    (cerbos/policies/model.yaml), so it is fixed at issuance. The key may call every
    governed model at LiteLLM; Cerbos decides per request which one it may actually use.
    """
    key_id = uid()
    generated = lite_request(
        "/key/generate",
        {
            "key_alias": upstream_alias(key_id),
            "models": MODELS,
            "max_budget": float(amount),
            "rpm_limit": rpm,
            "tpm_limit": tpm,
            "duration": f"{days}d",
            # LiteLLM only lets keys reach listed MCP servers; Cerbos then decides per tool.
            "object_permission": {"mcp_servers": MCP_SERVERS},
            "metadata": {
                "display_name": name,
                "key_id": key_id,
                "owner_id": owner.id,
                "team_id": asset.team_id or "",
                "department_id": asset.department_id,
                "asset_id": asset.id,
                **(extra_metadata or {}),
            },
        },
    )
    token = generated.get("key")
    if not isinstance(token, str) or not token.startswith("sk-"):
        raise HTTPException(503, "LiteLLM returned an invalid key; approval was not completed")
    return ApiKey(
        id=key_id,
        name=name,
        owner_id=owner.id,
        asset_id=asset.id,
        department_id=asset.department_id,
        team_id=asset.team_id,
        token_hash=token_hash(token),
        encrypted_token=cipher().encrypt(token.encode()).decode(),
        prefix=token[:7] + "…" + token[-4:],
        models=list(MODELS),
        rpm=rpm,
        tpm=tpm,
        expires_at=now() + timedelta(days=days),
    )


def maximum_cost(body):
    # Supported models have byte-based input metering and a hard output token limit.
    # No tools, images, n>1, retries, streaming, or hidden tokens. Real providers must
    # be added with a verified tokenizer/pricing contract.
    price = PRICING.get(body.model)
    if price is None:
        raise HTTPException(422, "This model has no configured price")
    input_tokens = sum(len(m.content.encode("utf-8")) + 16 for m in body.messages) + 32
    if input_tokens > 16000:
        raise HTTPException(422, "Input exceeds the supported context limit")
    return (
        input_tokens * price["input"] + body.max_tokens * price["output"],
        input_tokens + body.max_tokens,
    )


def actual_cost(model, input_used, output_used):
    price = PRICING[model]
    return input_used * price["input"] + output_used * price["output"]


def forward_completion(token, body):
    """Send the request to LiteLLM. Returns the JSON body and LiteLLM's response headers."""
    with httpx.Client(timeout=60) as client:
        response = client.post(
            f"{settings().litellm_url}/v1/chat/completions",
            headers={"Authorization": f"Bearer {token}"},
            json=body.litellm_body(),
        )
        response.raise_for_status()
        return response.json(), dict(response.headers)


def cerbos_headers(headers):
    """The decision LiteLLM's Cerbos guard attached to a response (infra/cerbos_guard.py)."""
    try:
        obligations = json.loads(headers.get("x-cerbos-obligations") or "{}")
    except ValueError:
        obligations = {}
    return {
        "effect": headers.get("x-cerbos-decision", ""),
        "rule": headers.get("x-cerbos-rule") or None,
        "reason": headers.get("x-cerbos-reason", ""),
        "obligations": obligations if isinstance(obligations, dict) else {},
    }


def answered_model(result, headers, requested):
    """The model that actually answered, which differs when Cerbos downgraded the request."""
    model = headers.get("x-litellm-model-group") or result.get("model") or requested
    if model not in PRICING:
        raise ValueError("Response came from an unpriced model")
    return model


def guard_rejection(error):
    """Return the Cerbos guard's decision if LiteLLM rejected the call before any provider.

    Only a 403/503 whose error message is the guard's own JSON qualifies. Every other
    failure leaves the provider outcome uncertain.
    """
    if not isinstance(error, httpx.HTTPStatusError):
        return None
    if error.response.status_code not in (403, 503):
        return None
    try:
        message = error.response.json()["error"]["message"]
        decision = json.loads(message)
    except (ValueError, KeyError, TypeError):
        return None
    if not isinstance(decision, dict) or decision.get("marker") != GUARD_MARKER:
        return None
    return {
        "status": error.response.status_code,
        "rule": decision.get("rule"),
        "reason": str(decision.get("reason") or ""),
        "resource": str(decision.get("resource") or ""),
    }


def key_principal(key):
    """The API key as LiteLLM's Cerbos guard presents it (infra/cerbos_guard.py)."""
    return {
        "id": f"key:{key.id}",
        "roles": ["api_key"],
        "attr": {
            "owner_id": key.owner_id,
            "team_id": key.team_id or "",
            "department_id": key.department_id,
            "asset_id": key.asset_id,
        },
    }


def model_resource(model, max_tokens, data_classification="internal"):
    return {
        "kind": "model",
        "id": model,
        "attr": {
            "tier": MODEL_TIERS.get(model, "unknown"),
            "max_tokens": max_tokens,
            "data_classification": data_classification,
        },
    }


def step(trace, name, status, **detail):
    if trace is not None:
        trace.append({"name": name, "status": status, **detail})


def complete(token, body, idempotency_key, trace=None):
    """Run one governed completion. When `trace` is a list, every step is recorded in it."""
    fingerprint = hashlib.sha256(json.dumps(body.model_dump(), sort_keys=True).encode()).hexdigest()
    amount, token_count = maximum_cost(body)
    with SessionLocal() as db:
        key = db.scalar(select(ApiKey).where(ApiKey.token_hash == token_hash(token)))
        if not key or key.status != "active" or key.expires_at <= now():
            step(
                trace, "Authenticate API key", "deny", reason="Key is invalid, expired or revoked."
            )
            raise HTTPException(401, "API key is invalid, expired, or revoked")
        owner, asset = db.get(User, key.owner_id), db.get(Asset, key.asset_id)
        if not owner or not owner.active or not asset:
            step(trace, "Authenticate API key", "deny", reason="Owner or agent is unavailable.")
            raise HTTPException(403, "API key owner or agent is unavailable")
        step(trace, "Authenticate API key", "ok", detail=f"{key.name} · owner {owner.name}")
        # Authorization is evaluated before any row lock is taken so Cerbos latency
        # never stalls other gateway requests or control-plane mutations.
        decision = explain(principal(owner), [asset_resource(asset)], ["use"])[asset.id]["use"]
        step(
            trace,
            "Cerbos in the gateway: may the owner use this agent?",
            decision["effect"],
            rule=decision["rule"],
            reason=decision["reason"],
            detail=f"principal {owner.id} · resource asset:{asset.id} · action use",
        )
        if decision["effect"] != "allow":
            raise HTTPException(403, "Cerbos denied this action for your role and scope")
        if body.model not in key.models:
            step(trace, "Key model list", "deny", reason="This key was not issued for this model.")
            raise HTTPException(403, "This key cannot access the requested model")
        lock_mutation(db)
        db.expire_all()  # Re-read every row under the lock.
        key = db.scalar(select(ApiKey).where(ApiKey.id == key.id).with_for_update())
        if not key or key.status != "active" or key.expires_at <= now():
            raise HTTPException(401, "API key is invalid, expired, or revoked")
        if asset.status != "active":
            raise HTTPException(403, "API key owner or agent is unavailable")
        existing = db.scalar(
            select(Reservation).where(
                Reservation.key_id == key.id, Reservation.idempotency_key == idempotency_key
            )
        )
        if existing:
            if existing.fingerprint != fingerprint:
                raise HTTPException(409, "Idempotency key was already used for a different request")
            if existing.status == "settled" and existing.response:
                step(trace, "Idempotent replay", "ok", detail="Returned the stored response.")
                return existing.response
            raise HTTPException(
                409,
                "This request is in flight or requires reconciliation; it will not be sent again",
            )
        count, tokens = db.execute(
            select(func.count(), func.coalesce(func.sum(Reservation.tokens), 0)).where(
                Reservation.key_id == key.id, Reservation.created_at >= now() - timedelta(minutes=1)
            )
        ).one()
        if count >= key.rpm or tokens + token_count > key.tpm:
            step(trace, "Key rate limit", "deny", reason="Requests or tokens per minute exceeded.")
            raise HTTPException(429, "API key rate limit reached; retry after the current minute")
        ids = [
            "organization",
            f"department:{key.department_id}",
            f"asset:{asset.id}",
            f"key:{key.id}",
        ]
        if key.team_id:
            ids.append(f"team:{key.team_id}")
        budgets = db.scalars(
            select(Budget).where(Budget.id.in_(ids)).order_by(Budget.id).with_for_update()
        ).all()
        if len(budgets) != len(ids):
            raise HTTPException(503, "A required budget is missing; request blocked")
        for budget in budgets:
            if budget.spent_micros + budget.reserved_micros + amount > budget.limit_micros:
                step(
                    trace,
                    "Reserve budget at every level",
                    "deny",
                    reason=f"{budget.scope.capitalize()} budget has insufficient unreserved funds.",
                )
                raise HTTPException(
                    429, f"{budget.scope.capitalize()} budget has insufficient unreserved funds"
                )
        for budget in budgets:
            budget.reserved_micros += amount
        reservation = Reservation(
            key_id=key.id,
            idempotency_key=idempotency_key,
            fingerprint=fingerprint,
            budget_ids=ids,
            amount_micros=amount,
            tokens=token_count,
        )
        db.add(reservation)
        db.flush()
        reservation_id, owner_id, dept_id, team_id = (
            reservation.id,
            owner.id,
            key.department_id,
            key.team_id,
        )
        guard_principal = key_principal(key)
        bus.emit(
            db, "budget.reserved", owner.id, reservation.id, dept_id, team_id, amount_micros=amount
        )
        db.commit()
    step(
        trace,
        "Reserve budget at every level",
        "ok",
        detail=f"Reserved the maximum possible cost (${amount / 1_000_000:.6f}) on "
        + ", ".join(ids),
    )

    try:
        result, response_headers = forward_completion(token, body)
        model_used = answered_model(result, response_headers, body.model)
        usage = result["usage"]
        input_used, output_used = usage["prompt_tokens"], usage["completion_tokens"]
        if (
            type(input_used) is not int
            or type(output_used) is not int
            or min(input_used, output_used) < 0
        ):
            raise ValueError("Invalid usage")
        actual = actual_cost(model_used, input_used, output_used)
        if actual > amount or output_used > body.max_tokens:
            raise ValueError("Provider exceeded the supported cost contract")
    except (httpx.HTTPError, ValueError, KeyError, TypeError) as error:
        rejection = guard_rejection(error)
        if rejection:
            # LiteLLM's Cerbos guard rejected the call before any provider was contacted,
            # so nothing can have been charged: release the full reservation.
            release(reservation_id, amount, owner_id, dept_id, team_id, rejection, body.model)
            step(
                trace,
                "Cerbos inside LiteLLM: may this key invoke this model?",
                "deny",
                rule=rejection["rule"],
                reason=rejection["reason"],
                detail=f"principal {guard_principal['id']} · resource model:{body.model}"
                f" · max_tokens {body.max_tokens}",
            )
            step(
                trace, "Release reservation", "ok", detail="No provider call, so nothing was spent."
            )
            raise HTTPException(
                rejection["status"],
                f"Cerbos inside LiteLLM denied this call: {rejection['reason']}",
            ) from None
        # An HTTP timeout/error does NOT prove that a provider did not charge.
        # Keep the full reservation and never automatically retry or release it.
        with SessionLocal.begin() as db:
            lock_mutation(db)
            reservation = db.get(Reservation, reservation_id)
            reservation.status = "uncertain"
            bus.emit(
                db,
                "gateway.reconciliation_required",
                owner_id,
                reservation_id,
                dept_id,
                team_id,
                reserved_micros=amount,
            )
        step(trace, "Provider", "error", reason="Outcome uncertain; funds stay reserved.")
        raise HTTPException(
            502,
            "The provider outcome is uncertain. Funds remain reserved and this request will not be retried automatically.",
        ) from None

    if trace is not None:
        decision = cerbos_headers(response_headers)
        if not decision["effect"]:  # Older LiteLLM image without the headers hook.
            decision = explain(
                guard_principal, [model_resource(body.model, body.max_tokens)], ["invoke"]
            )[body.model]["invoke"]
            decision["obligations"] = {}
        applied = ", ".join(f"{k} → {v}" for k, v in decision["obligations"].items())
        step(
            trace,
            "Cerbos inside LiteLLM: may this key invoke this model?",
            "allow",
            rule=decision["rule"],
            reason=decision["reason"],
            obligations=decision["obligations"],
            detail=f"principal {guard_principal['id']} · resource model:{body.model}"
            f" · max_tokens {body.max_tokens} · {body.data_classification} data"
            + (f" · obligations applied: {applied}" if applied else ""),
        )
        step(
            trace,
            "Provider",
            "ok",
            model=model_used,
            detail=f"Answered by {model_used}: {input_used} input and {output_used} output tokens",
        )

    with SessionLocal.begin() as db:
        lock_mutation(db)
        reservation = db.get(Reservation, reservation_id)
        budgets = db.scalars(
            select(Budget)
            .where(Budget.id.in_(reservation.budget_ids))
            .order_by(Budget.id)
            .with_for_update()
        ).all()
        for budget in budgets:
            budget.reserved_micros -= amount
            budget.spent_micros += actual
        reservation.status, reservation.actual_micros, reservation.response = (
            "settled",
            actual,
            result,
        )
        bus.emit(
            db,
            "gateway.completed",
            owner_id,
            reservation_id,
            dept_id,
            team_id,
            cost_micros=actual,
            model=body.model,
        )
    step(
        trace,
        "Settle actual cost",
        "ok",
        detail=f"Charged ${actual / 1_000_000:.6f}; the rest of the reservation was released.",
    )
    return result


def release(reservation_id, amount, owner_id, dept_id, team_id, rejection, model):
    with SessionLocal.begin() as db:
        lock_mutation(db)
        reservation = db.get(Reservation, reservation_id)
        budgets = db.scalars(
            select(Budget)
            .where(Budget.id.in_(reservation.budget_ids))
            .order_by(Budget.id)
            .with_for_update()
        ).all()
        for budget in budgets:
            budget.reserved_micros -= amount
        reservation.status, reservation.actual_micros = "denied", 0
        bus.emit(
            db,
            "gateway.policy_denied",
            owner_id,
            reservation_id,
            dept_id,
            team_id,
            model=model,
            rule=rejection["rule"],
            reason=rejection["reason"],
        )
