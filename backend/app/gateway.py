"""The governed gateway: the public entry point for AI calls.

The gateway checks the key, asks Cerbos whether the owner may use the agent, and makes
retries idempotent. The money is not kept here: LiteLLM's Cerbos guard reserves and
settles budget through the ledger (app/ledger.py) for every call, including calls that
skip this gateway, so no path can spend past a cap.
"""

import hashlib
import json
import logging
from datetime import timedelta

import httpx
from cryptography.fernet import Fernet
from fastapi import HTTPException
from sqlalchemy import select

from . import ledger
from .config import settings
from .db import SessionLocal
from .ledger import PRICING, LedgerRefusal, actual_cost, lock_mutation  # noqa: F401
from .models import ApiKey, Asset, Reservation, User, now, uid
from .policy import asset_resource, explain, principal

MODEL_TIERS = {"governed-demo": "standard", "governed-premium": "premium"}
MODELS = list(PRICING)
# MCP servers proxied by LiteLLM (infra/litellm.yaml).
MCP_SERVERS = ["knowledge"]
GUARD_MARKER = "cerbos_guard"
BUDGET_STEP = "Budget inside LiteLLM: reserve at every level"
CERBOS_STEP = "Cerbos inside LiteLLM: may this key invoke this model?"
logger = logging.getLogger(__name__)


def cipher():
    return Fernet(settings().encryption_key.encode())


def token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


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


def input_tokens(body):
    return ledger.estimate_input_tokens(
        sum(len(m.content.encode("utf-8")) for m in body.messages), len(body.messages)
    )


def maximum_cost(body):
    """The most this request can cost, as the ledger inside LiteLLM will reserve it."""
    # Supported models have byte-based input metering and a hard output token limit.
    # No tools, images, n>1, retries or hidden tokens; streams settle from final usage. Real providers must
    # be added with a verified tokenizer/pricing contract.
    tokens = input_tokens(body)
    try:
        return ledger.maximum_cost(body.model, tokens, body.max_tokens), tokens + body.max_tokens
    except LedgerRefusal as refusal:
        raise HTTPException(refusal.status, refusal.reason) from None


def forward_completion(token, body, metadata=None):
    """Send the request to LiteLLM. Returns the JSON body and LiteLLM's response headers."""
    payload = body.litellm_body()
    payload["metadata"].update(metadata or {})
    with httpx.Client(timeout=60) as client:
        response = client.post(
            f"{settings().litellm_url}/v1/chat/completions",
            headers={"Authorization": f"Bearer {token}"},
            json=payload,
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

    Only an error whose message is the guard's own JSON qualifies: a Cerbos refusal or a
    ledger refusal (kind "budget"). Every other failure leaves the provider outcome
    uncertain.
    """
    if not isinstance(error, httpx.HTTPStatusError):
        return None
    if not (400 <= error.response.status_code < 500 or error.response.status_code == 503):
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
        "kind": str(decision.get("kind") or "model"),
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


def _admit(token, body, idempotency_key, trace):
    """The gateway's own checks. Returns (stored answer to replay or None, context)."""
    fingerprint = hashlib.sha256(json.dumps(body.model_dump(), sort_keys=True).encode()).hexdigest()
    maximum_cost(body)  # Unpriced models and oversized input fail before anything else.
    with SessionLocal() as db:
        key = db.scalar(select(ApiKey).where(ApiKey.token_hash == token_hash(token)))
        if not key or key.status != "active" or key.expires_at <= now():
            step(
                trace, "Authenticate API key", "deny", reason="Key is invalid, expired or revoked."
            )
            raise HTTPException(401, "API key is invalid, expired, or revoked")
        owner, asset = db.get(User, key.owner_id), db.get(Asset, key.asset_id)
        if not owner or not owner.active or not asset or asset.status != "active":
            step(trace, "Authenticate API key", "deny", reason="Owner or agent is unavailable.")
            raise HTTPException(403, "API key owner or agent is unavailable")
        step(trace, "Authenticate API key", "ok", detail=f"{key.name} · owner {owner.name}")
        decision = explain(principal(owner), [asset_resource(asset)], ["use"], source="gateway")[
            asset.id
        ]["use"]
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
        existing = db.scalar(
            select(Reservation).where(
                Reservation.key_id == key.id, Reservation.idempotency_key == idempotency_key
            )
        )
        if existing:
            if body.stream:
                raise HTTPException(
                    409, "Streamed answers are not replayed; send a new Idempotency-Key"
                )
            if existing.fingerprint != fingerprint:
                raise HTTPException(409, "Idempotency key was already used for a different request")
            if existing.status == "settled" and existing.response:
                step(trace, "Idempotent replay", "ok", detail="Returned the stored response.")
                return existing.response, None
            raise HTTPException(
                409,
                "This request is in flight or requires reconciliation; it will not be sent again",
            )
        key_id, guard_principal = key.id, key_principal(key)

    # LiteLLM's Cerbos guard decides, applies obligations, then reserves budget at every
    # level through the ledger before any provider is called.
    return None, {
        "key_id": key_id,
        "principal": guard_principal,
        "metadata": {
            "idempotency_key": idempotency_key,
            "fingerprint": fingerprint,
            "gateway_signature": ledger.gateway_signature(key_id, idempotency_key),
        },
        "detail": f"principal {guard_principal['id']} · resource model:{body.model}"
        f" · max_tokens {body.max_tokens} · {body.data_classification} data",
    }


def _litellm_failure(error, trace, request_detail):
    """Turn a failed LiteLLM call into the right HTTP error, recording why in the trace."""
    rejection = guard_rejection(error)
    if rejection and rejection["kind"] == "budget":
        step(trace, CERBOS_STEP, "allow", detail=request_detail)
        step(trace, BUDGET_STEP, "deny", reason=rejection["reason"])
        return HTTPException(rejection["status"], rejection["reason"])
    if rejection:
        step(
            trace,
            CERBOS_STEP,
            "deny",
            rule=rejection["rule"],
            reason=rejection["reason"],
            detail=request_detail,
        )
        step(trace, BUDGET_STEP, "skipped", detail="Refused before any budget was reserved.")
        return HTTPException(
            rejection["status"], f"Cerbos inside LiteLLM denied this call: {rejection['reason']}"
        )
    # An HTTP timeout/error does NOT prove that a provider did not charge. The ledger
    # inside LiteLLM keeps the reservation; this request is never retried automatically.
    step(trace, "Provider", "error", reason="Outcome uncertain; funds stay reserved.")
    return HTTPException(
        502,
        "The provider outcome is uncertain. Funds remain reserved and this request will not be retried automatically.",
    )


def open_stream(token, body, metadata):
    """Start a streamed completion at LiteLLM: (headers, raw chunks).

    LiteLLM's Cerbos guard decides and reserves budget before the first byte, so a refusal
    arrives as an ordinary error response and is raised here, before anything is streamed.
    """
    client = httpx.Client(timeout=httpx.Timeout(60, connect=10))
    payload = body.litellm_body()
    payload["metadata"].update(metadata)
    try:
        response = client.send(
            client.build_request(
                "POST",
                f"{settings().litellm_url}/v1/chat/completions",
                headers={"Authorization": f"Bearer {token}"},
                json=payload,
            ),
            stream=True,
        )
        if response.status_code >= 400:
            response.read()
            response.close()
            response.raise_for_status()
    except BaseException:
        client.close()
        raise

    def chunks():
        try:
            yield from response.iter_raw()
        finally:  # A client that disconnects closes this, and LiteLLM holds the funds.
            response.close()
            client.close()

    return dict(response.headers), chunks()


def stream_completion(token, body, idempotency_key, trace=None):
    """Admit a streamed completion and start it: (LiteLLM headers, chunks, context).

    The ledger inside LiteLLM settles the real cost from the stream's final usage chunk,
    before the stream ends. Streamed answers are not stored, so they are never replayed.
    """
    _, context = _admit(token, body, idempotency_key, trace)
    try:
        headers, chunks = open_stream(token, body, context["metadata"])
    except httpx.HTTPError as error:
        raise _litellm_failure(error, trace, context["detail"]) from None
    if trace is not None:
        decision = cerbos_headers(headers)
        step(
            trace,
            CERBOS_STEP,
            "allow",
            rule=decision["rule"],
            reason=decision["reason"],
            obligations=decision["obligations"],
            detail=context["detail"],
        )
        reserved = headers.get("x-ai-spine-reserved-micros") or "0"
        step(
            trace,
            BUDGET_STEP,
            "ok",
            detail=f"Reserved the maximum possible cost (${int(reserved) / 1_000_000:.6f}) "
            "on every budget level before the stream started",
        )
    return headers, chunks, context


def ledger_entry(key_id, idempotency_key):
    """The reservation the ledger inside LiteLLM made for this call, if any."""
    with SessionLocal() as db:
        return db.scalar(
            select(Reservation).where(
                Reservation.key_id == key_id, Reservation.idempotency_key == idempotency_key
            )
        )


def complete(token, body, idempotency_key, trace=None):
    """Run one governed completion. When `trace` is a list, every step is recorded in it."""
    if body.stream:
        raise HTTPException(422, "Use stream_completion for streamed requests")
    replay, context = _admit(token, body, idempotency_key, trace)
    if replay is not None:
        return replay
    key_id, guard_principal = context["key_id"], context["principal"]
    cerbos_step, request_detail = CERBOS_STEP, context["detail"]
    try:
        result, response_headers = forward_completion(token, body, context["metadata"])
        model_used = answered_model(result, response_headers, body.model)
    except (httpx.HTTPError, ValueError, KeyError, TypeError) as error:
        raise _litellm_failure(error, trace, request_detail) from None

    with SessionLocal.begin() as db:
        reservation = db.scalar(
            select(Reservation)
            .where(Reservation.key_id == key_id, Reservation.idempotency_key == idempotency_key)
            .with_for_update()
        )
        if not reservation or reservation.status != "settled":
            # LiteLLM answered without a settled charge: never hand out an unbilled answer.
            logger.error("Answered call without a settled ledger entry: key=%s", key_id)
            raise HTTPException(502, "The ledger did not record this call; it was not returned")
        reservation.response = result  # For idempotent replay of this exact answer.
        reserved, charged = reservation.amount_micros, reservation.actual_micros
        budget_ids = list(reservation.budget_ids)

    if trace is not None:
        decision = cerbos_headers(response_headers)
        if not decision["effect"]:  # Older LiteLLM image without the headers hook.
            decision = explain(
                guard_principal,
                [model_resource(body.model, body.max_tokens)],
                ["invoke"],
                source="playground",
            )[body.model]["invoke"]
            decision["obligations"] = {}
        applied = ", ".join(f"{k} → {v}" for k, v in decision["obligations"].items())
        step(
            trace,
            cerbos_step,
            "allow",
            rule=decision["rule"],
            reason=decision["reason"],
            obligations=decision["obligations"],
            detail=request_detail + (f" · obligations applied: {applied}" if applied else ""),
        )
        step(
            trace,
            BUDGET_STEP,
            "ok",
            detail=f"Reserved the maximum possible cost (${reserved / 1_000_000:.6f}) on "
            + ", ".join(budget_ids),
        )
        usage = result.get("usage") or {}
        step(
            trace,
            "Provider",
            "ok",
            model=model_used,
            detail=f"Answered by {model_used}: {usage.get('prompt_tokens')} input and "
            f"{usage.get('completion_tokens')} output tokens",
        )
        step(
            trace,
            "Settle actual cost",
            "ok",
            detail=f"Charged ${charged / 1_000_000:.6f} inside LiteLLM; the rest of the "
            "reservation was released.",
        )
    return result
