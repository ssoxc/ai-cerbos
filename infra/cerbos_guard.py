"""Cerbos authorization inside LiteLLM, through four LiteLLM hooks.

1. async_pre_call_hook, model calls: may this API key invoke this model with these
   parameters and this data classification? Cerbos can deny, allow, or allow with
   obligations (downgrade the model, cap max_tokens) that are applied to the request.
2. async_pre_call_hook, MCP tool calls (LiteLLM's MCP gateway): may this key call this
   tool on this server, given the tool's risk?
3. async_filter_listed_models: GET /v1/models lists only models Cerbos lets the key see.
4. async_post_call_response_headers_hook: every response carries the Cerbos decision
   (x-cerbos-*), so callers and the dashboard see the real rule that applied.

The principal is always the API key itself (role api_key). Its owner, team, department
and agent are written into the key's metadata when the governed API issues it. Calls
without that metadata, including master-key calls, are denied. Any Cerbos failure denies
the call (fail closed). Policies: cerbos/policies/model.yaml and mcp_tool.yaml.

Rejections carry the marker "cerbos_guard" so the gateway can tell a definitive policy
rejection (no provider contacted, safe to release reserved budget) from other errors.
"""

import json
import os
import uuid

import httpx
from fastapi import HTTPException
from litellm.integrations.custom_logger import CustomLogger

CERBOS_URL = os.environ.get("CERBOS_URL", "http://cerbos:3592")
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


class CerbosGuard(CustomLogger):
    def __init__(self):
        super().__init__()
        self.client = httpx.AsyncClient(timeout=5)

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
        model = str(data.get("model") or "")
        max_tokens = int(data.get("max_tokens") or data.get("max_completion_tokens") or DEFAULT_MAX_TOKENS)
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
        # Remembered for the response headers hook below.
        data.setdefault("metadata", {})["cerbos"] = {
            **decision,
            "obligations": applied,
            "requested_model": model,
            "data_classification": classification,
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
        return {
            "x-cerbos-decision": decision["effect"],
            "x-cerbos-rule": decision["rule"] or "",
            "x-cerbos-reason": decision["reason"].encode("ascii", "replace").decode()[:300],
            "x-cerbos-obligations": json.dumps(decision["obligations"]),
            "x-cerbos-requested-model": decision["requested_model"],
            "x-cerbos-data-classification": decision["data_classification"],
        }


proxy_handler_instance = CerbosGuard()
