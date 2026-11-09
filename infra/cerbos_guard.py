"""Cerbos authorization and budget enforcement inside LiteLLM.

1. async_pre_call_hook, model calls: may this API key invoke this model with these
   parameters and this data classification? Cerbos can deny, allow, or allow with
   obligations (downgrade the model, cap max_tokens) that are applied to the request.
2. async_pre_call_hook, MCP tool calls (LiteLLM's MCP gateway): may this key call this
   tool on this server, given the tool's risk?
3. async_filter_listed_models: GET /v1/models lists only models Cerbos lets the key see.
4. async_post_call_response_headers_hook: every response carries the Cerbos decision
   (x-cerbos-*), so callers and the dashboard see the real rule that applied.
5. Budgets. After Cerbos allows a model call and its obligations are applied, the guard
   reserves the call's maximum cost at every level (key, agent, team, department,
   organization) through the AI spine's ledger (backend/app/ledger.py). The success hook
   settles the actual cost; for a streamed answer, the stream hook settles it from the
   final usage chunk before the stream closes. The failure hook releases the reservation,
   or holds it when the provider outcome is unknown, as does a stream that stops early. Because this runs inside LiteLLM, a key holder who
   skips the governed gateway is still held to every cap.

The principal is always the API key itself (role api_key). Its owner, team, department
and agent are written into the key's metadata when the governed API issues it. Calls
without that metadata, including master-key calls, are denied. Any Cerbos failure denies
the call (fail closed). Policies: cerbos/policies/model.yaml and mcp_tool.yaml.

Rejections carry the marker "cerbos_guard" so the gateway can tell a definitive
rejection (no provider contacted, nothing charged) from other errors. Kind "budget" marks a
ledger refusal; the ledger being unreachable also refuses the call (fail closed).
"""

import asyncio
import json
import logging
import os
import uuid

import httpx
from fastapi import HTTPException
from litellm.integrations.custom_logger import CustomLogger

CERBOS_URL = os.environ.get("CERBOS_URL", "http://cerbos:3592")
LEDGER_URL = os.environ.get("LEDGER_URL", "http://api:8000")
LEDGER_TOKEN = os.environ.get("LEDGER_TOKEN", "")
logger = logging.getLogger("cerbos_guard")
MARKER = "cerbos_guard"
# Tier per public model name. Mirrors infra/litellm.yaml.
TIERS = {"governed-demo": "standard", "governed-premium": "premium"}
DEFAULT_MAX_TOKENS = 2048  # A missing limit is treated as the largest allowed request.
CLASSIFICATIONS = ("public", "internal", "confidential")
PRINCIPAL_ATTRS = ("owner_id", "team_id", "department_id", "asset_id")
# MCP servers proxied by LiteLLM: the team that owns each one in the asset registry,
# and each tool's risk from its MCP annotations (readOnlyHint / destructiveHint).
MCP_SERVERS = {
    "knowledge": {
        "owner_team": "agents",
        "tools": {"search_docs": "read", "add_note": "write", "delete_collection": "destructive"},
    }
}


def reject(status: int, reason: str, rule: str | None = None, kind: str = "model", resource: str = ""):
    payload = {
        "marker": MARKER,
        "decision": "deny",
        "kind": kind,
        "resource": resource,
        "rule": rule,
        "reason": reason,
    }
    raise HTTPException(status_code=status, detail=json.dumps(payload))


def principal_for(user_api_key_dict) -> dict | None:
    metadata = getattr(user_api_key_dict, "metadata", None) or {}
    if not metadata.get("key_id"):
        return None
    return {
        "id": f"key:{metadata['key_id']}",
        "roles": ["api_key"],
        "attr": {name: str(metadata.get(name) or "") for name in PRINCIPAL_ATTRS},
    }


def explain(result: dict, action: str) -> dict:
    """The deciding rule for `action`, with its reason and any obligations."""
    effect = "allow" if result["actions"].get(action) == "EFFECT_ALLOW" else "deny"
    for entry in result.get("outputs") or []:
        value = entry.get("val")
        if entry.get("action") == action and isinstance(value, dict) and value.get("effect") == effect:
            return {
                "effect": effect,
                "rule": entry.get("src", "").rsplit("#", 1)[-1],
                "reason": str(value.get("reason", "")),
                "obligations": value.get("obligations") or {},
            }
    return {
        "effect": effect,
        "rule": None,
        "reason": "No rule matched, so Cerbos denies by default.",
        "obligations": {},
    }


def input_size(data: dict) -> tuple[int, int]:
    """Bytes of input and message count, for the ledger's maximum-cost estimate."""
    messages = data.get("messages")
    if isinstance(messages, list):
        size = 0
        for message in messages:
            content = message.get("content") if isinstance(message, dict) else message
            size += len(content.encode() if isinstance(content, str) else json.dumps(content).encode())
        return size, len(messages)
    payload = data.get("input") or data.get("prompt") or ""
    return len(payload.encode() if isinstance(payload, str) else json.dumps(payload).encode()), 1


def usage_of(response) -> tuple[int, int] | None:
    usage = getattr(response, "usage", None)
    if usage is None and isinstance(response, dict):
        usage = response.get("usage")
    if usage is None:
        return None
    read = usage.get if isinstance(usage, dict) else lambda name: getattr(usage, name, None)
    prompt, completion = read("prompt_tokens"), read("completion_tokens") or 0
    return (prompt, completion) if isinstance(prompt, int) and isinstance(completion, int) else None


class CerbosGuard(CustomLogger):
    def __init__(self):
        super().__init__()
        self.client = httpx.AsyncClient(timeout=5, headers={"X-Ai-Spine-Source": "litellm"})
        self.pending: set[asyncio.Task] = set()  # Ledger calls that must outlive a cancelled stream.
        self.ledger = httpx.AsyncClient(
            base_url=f"{LEDGER_URL}/internal/ledger", timeout=10, headers={"X-Ledger-Token": LEDGER_TOKEN}
        )

    # 5: budgets -------------------------------------------------------------------------
    async def reserve(self, key_id: str, data: dict, classification: str) -> dict:
        metadata = data.get("metadata") or {}
        size, count = input_size(data)
        # The gateway sends its idempotency key and a signature; direct calls get a fresh id.
        idempotency_key = str(metadata.get("idempotency_key") or data.get("litellm_call_id") or uuid.uuid4())
        try:
            response = await self.ledger.post(
                "/reserve",
                json={
                    "key_id": key_id,
                    "model": data["model"],
                    "max_tokens": int(data.get("max_tokens") or data.get("max_completion_tokens") or DEFAULT_MAX_TOKENS),
                    "input_bytes": size,
                    "message_count": count,
                    "idempotency_key": idempotency_key[:100],
                    "gateway_signature": str(metadata.get("gateway_signature") or "")[:64],
                    "fingerprint": str(metadata.get("fingerprint") or "")[:64],
                    "data_classification": classification,
                },
            )
        except httpx.HTTPError:
            reject(503, "The budget ledger is unavailable, so LiteLLM denies the call (fail closed).", kind="budget")
        if response.status_code == 200:
            return response.json()
        try:
            detail = response.json().get("detail")
        except ValueError:
            detail = None
        if not isinstance(detail, dict) or "reason" not in detail:
            # Not a ledger decision (a wrong token, a crash): refuse rather than spend unchecked.
            reject(503, "The budget ledger is unavailable, so LiteLLM denies the call (fail closed).", kind="budget")
        reject(response.status_code, str(detail["reason"]), kind="budget", resource=str(detail.get("scope", "")))

    async def ledger_call(self, reservation_id: str, action: str, body: dict) -> dict | None:
        # Settling must not be lost to a brief outage: retry a few times. If it still fails,
        # the reservation stays held, which errs on the side of spending less.
        for attempt in range(3):
            try:
                response = await self.ledger.post(f"/{reservation_id}/{action}", json=body)
                response.raise_for_status()
                return response.json()
            except (httpx.HTTPError, ValueError):
                await asyncio.sleep(0.2 * (attempt + 1))
        logger.error("Ledger %s failed for reservation %s; funds stay reserved", action, reservation_id)
        return None

    async def settle(self, data: dict, usage: tuple[int, int] | None, unfinished: str = "") -> None:
        """Charge the call once: the real cost from usage, or hold the funds without it."""
        metadata = data.get("metadata") or {}
        ledger, decision = metadata.get("ledger"), metadata.get("cerbos") or {}
        if not ledger or ledger.get("closed"):
            return
        ledger["closed"] = True
        if usage is None or unfinished:
            reason = unfinished or "The provider reported no usage."
            await self.ledger_call(ledger["reservation_id"], "hold", {"reason": reason})
            return
        result = await self.ledger_call(
            ledger["reservation_id"],
            "settle",
            {
                "answered_model": data["model"],
                "input_tokens": usage[0],
                "output_tokens": usage[1],
                "requested_model": decision.get("requested_model", data["model"]),
                "max_tokens": int(data.get("max_tokens") or DEFAULT_MAX_TOKENS),
                "data_classification": decision.get("data_classification", "internal"),
                "obligations": decision.get("obligations") or {},
            },
        )
        ledger["charged_micros"] = (result or {}).get("actual_micros")

    async def async_post_call_success_hook(self, data, user_api_key_dict, response):
        if not data.get("stream"):  # Streams settle in the stream hook below.
            await self.settle(data, usage_of(response))
        return response

    async def async_post_call_streaming_iterator_hook(self, user_api_key_dict, response, request_data):
        """Pass every chunk through, then settle from the last usage seen, before the stream closes.

        A stream that stops early (the client disconnected, or an error) may still have cost
        money at the provider, so its reservation is held for reconciliation, never released.
        """
        if not (request_data.get("metadata") or {}).get("ledger"):
            async for chunk in response:
                yield chunk
            return
        usage, finished = None, False
        try:
            async for chunk in response:
                usage = usage_of(chunk) or usage
                yield chunk
            finished = True
            await self.settle(request_data, usage)
        finally:
            if not finished:
                # Cancellation may interrupt an await here, so hold in a separate task.
                task = asyncio.get_running_loop().create_task(
                    self.settle(request_data, None, "The stream stopped before it finished; the provider may have charged.")
                )
                self.pending.add(task)
                task.add_done_callback(self.pending.discard)

    async def async_post_call_failure_hook(
        self, request_data, original_exception, user_api_key_dict, traceback_str=None
    ):
        ledger = (request_data.get("metadata") or {}).get("ledger")
        if not ledger or ledger.get("closed"):
            return
        ledger["closed"] = True
        status = getattr(original_exception, "status_code", None)
        timed_out = "timeout" in type(original_exception).__name__.lower() or status == 408
        if isinstance(status, int) and 400 <= status < 500 and not timed_out:
            # Refused before or by the provider without doing the work: nothing was charged.
            await self.ledger_call(ledger["reservation_id"], "release", {"reason": f"Refused with status {status}."})
        else:
            await self.ledger_call(
                ledger["reservation_id"], "hold", {"reason": "Provider outcome unknown; reconcile before releasing."}
            )

    async def check(self, principal: dict, resources: list[dict], action: str) -> list[dict]:
        try:
            response = await self.client.post(
                f"{CERBOS_URL}/api/check/resources",
                json={
                    "requestId": str(uuid.uuid4()),
                    "includeMeta": True,
                    "principal": principal,
                    "resources": [{"resource": r, "actions": [action]} for r in resources],
                },
            )
            response.raise_for_status()
            return response.json()["results"]
        except (httpx.HTTPError, ValueError, KeyError):
            reject(503, "Cerbos is unavailable, so LiteLLM denies the call (fail closed).")

    # 1 + 2: every model call and every MCP tool call ------------------------------------
    async def async_pre_call_hook(self, user_api_key_dict, cache, data, call_type):
        principal = principal_for(user_api_key_dict)
        if principal is None:
            reject(403, "Only governed virtual keys issued by ai-cerbos may call LiteLLM.")
        if str(call_type) in ("call_mcp_tool", "CallTypes.call_mcp_tool"):
            return await self.authorize_tool(principal, data)
        return await self.authorize_model(principal, data)

    async def authorize_model(self, principal: dict, data: dict) -> dict:
        if data.get("stream"):
            # The final chunk must carry the usage the ledger settles from.
            data["stream_options"] = {**(data.get("stream_options") or {}), "include_usage": True}
        model = str(data.get("model") or "")
        max_tokens = int(data.get("max_tokens") or data.get("max_completion_tokens") or DEFAULT_MAX_TOKENS)
        if not data.get("max_tokens") and not data.get("max_completion_tokens"):
            data["max_tokens"] = max_tokens  # Bound the provider by what the ledger reserves.
        metadata = data.get("metadata") or {}
        classification = str(metadata.get("data_classification") or "internal")
        if classification not in CLASSIFICATIONS:
            classification = "confidential"  # Unknown labels get the strictest treatment.
        resource = {
            "kind": "model",
            "id": model,
            "attr": {
                "tier": TIERS.get(model, "unknown"),
                "max_tokens": max_tokens,
                "data_classification": classification,
            },
        }
        decision = explain((await self.check(principal, [resource], "invoke"))[0], "invoke")
        if decision["effect"] != "allow":
            reject(403, decision["reason"], decision["rule"], resource=resource["id"])
        applied = {}
        obligations = decision["obligations"]
        if obligations.get("model") in TIERS and obligations["model"] != model:
            data["model"] = applied["model"] = obligations["model"]
        cap = obligations.get("max_tokens")
        if isinstance(cap, int | float) and int(cap) < max_tokens:
            data["max_tokens"] = applied["max_tokens"] = int(cap)
            if "max_completion_tokens" in data:
                data["max_completion_tokens"] = int(cap)
        # Remembered for the response headers hook below.
        data.setdefault("metadata", {})["cerbos"] = {
            **decision,
            "obligations": applied,
            "requested_model": model,
            "data_classification": classification,
        }
        # Budgets: reserve the final request's maximum cost at every level, or refuse.
        reservation = await self.reserve(principal["id"].removeprefix("key:"), data, classification)
        data["metadata"]["ledger"] = {
            "reservation_id": reservation["reservation_id"],
            "reserved_micros": reservation["amount_micros"],
        }
        return data

    async def authorize_tool(self, principal: dict, data: dict) -> dict:
        # LiteLLM calls this hook with two payload shapes for one tool call: the REST body
        # ({"name", "server_id", "arguments"}) and its own MCP payload ("mcp_tool_name",
        # "mcp_server_name"). Both are checked; either may deny.
        server = str(data.get("mcp_server_name") or "")
        tool = str(data.get("mcp_tool_name") or data.get("name") or "")
        for name in MCP_SERVERS:  # Tool names may be prefixed: "knowledge-search_docs".
            if tool.startswith(f"{name}-") and (not server or server == name):
                server, tool = name, tool[len(name) + 1 :]
        if not server:  # Identify the server by its tool when only an opaque id was sent.
            owners = [name for name, config in MCP_SERVERS.items() if tool in config["tools"]]
            server = owners[0] if len(owners) == 1 else ""
        config = MCP_SERVERS.get(server, {})
        resource = {
            "kind": "mcp_tool",
            "id": f"{server}/{tool}",
            "attr": {
                "server": server,
                "tool": tool,
                "risk": config.get("tools", {}).get(tool, "unknown"),
                "owner_team": config.get("owner_team", ""),
            },
        }
        decision = explain((await self.check(principal, [resource], "call"))[0], "call")
        if decision["effect"] != "allow":
            reject(403, decision["reason"], decision["rule"], kind="mcp_tool", resource=resource["id"])
        return data

    # 3: the model catalog ---------------------------------------------------------------
    async def async_filter_listed_models(self, user_api_key_dict, model_names):
        principal = principal_for(user_api_key_dict)
        if principal is None:
            return []
        names = [name for name in model_names if name in TIERS]
        if not names:
            return []
        resources = [
            {"kind": "model", "id": name, "attr": {"tier": TIERS[name], "max_tokens": 1, "data_classification": "public"}}
            for name in names
        ]
        results = await self.check(principal, resources, "list")
        return [r["resource"]["id"] for r in results if r["actions"].get("list") == "EFFECT_ALLOW"]

    # 4: the decision, on every response ------------------------------------------------------
    async def async_post_call_response_headers_hook(
        self, data, user_api_key_dict, response, request_headers=None, litellm_call_info=None
    ):
        decision = (data.get("metadata") or {}).get("cerbos")
        if not decision:
            return None
        ledger = (data.get("metadata") or {}).get("ledger") or {}
        return {
            "x-ai-spine-reservation": str(ledger.get("reservation_id", "")),
            "x-ai-spine-reserved-micros": str(ledger.get("reserved_micros", "")),
            "x-ai-spine-charged-micros": str(ledger.get("charged_micros", "")),
            "x-cerbos-decision": decision["effect"],
            "x-cerbos-rule": decision["rule"] or "",
            "x-cerbos-reason": decision["reason"].encode("ascii", "replace").decode()[:300],
            "x-cerbos-obligations": json.dumps(decision["obligations"]),
            "x-cerbos-requested-model": decision["requested_model"],
            "x-cerbos-data-classification": decision["data_classification"],
        }


proxy_handler_instance = CerbosGuard()
