"""Cerbos playground API: explore decisions, compare personas, edit policies, trace a
request through the gateway and LiteLLM, and reset the demo. Demo mode only.

These endpoints are deliberately NOT authorized through Cerbos: they exist to change and
inspect the Cerbos policies, so a policy edit must never be able to lock them out. They
require demo mode and a signed-in session instead.
"""

import json
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Literal

import httpx
import yaml
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import demo, policy_store, story
from .auth import current_user
from .config import settings
from .db import get_db
from .events import bus
from .gateway import (
    MODEL_TIERS,
    MODELS,
    answered_model,
    cerbos_headers,
    cipher,
    complete,
    forward_completion,
    guard_rejection,
    key_principal,
    model_resource,
)
from .models import ApiKey, Approval, Asset, Budget, Department, Team, User
from .policy import (
    approval_resource,
    asset_resource,
    budget_resource,
    department_resource,
    explain,
    key_resource,
    platform_resource,
    principal_from,
    team_resource,
)
from .scenarios import SCENARIOS
from .schemas import Completion, StrictModel
from .serialize import dump

router = APIRouter(prefix="/api")

KNOWN_ROLES = [
    "viewer",
    "developer",
    "developer_admin",
    "cost_center_admin",
    "executive_admin",
    "finance_admin",
    "api_key_approver",
]
KINDS = {
    "asset": "AI assets (agents, MCP servers, skills)",
    "approval": "Review requests",
    "api_key": "Issued API keys",
    "budget": "Spending caps",
    "team": "Teams",
    "department": "Operating units",
    "platform": "Dashboard areas",
    "model": "Models, checked inside LiteLLM",
    "mcp_tool": "MCP tools, checked inside LiteLLM",
}
KEY_KINDS = {"model", "mcp_tool"}  # Kinds whose principal is an API key, not a person.
DEFAULT_TRACE_TOKENS = 256
# Tools of the demo knowledge MCP server (backend/app/mcp_demo.py), with the risk their MCP
# annotations declare and the arguments the playground sends.
MCP_TOOLS = [
    {
        "name": "search_docs",
        "title": "Search documents",
        "risk": "read",
        "arguments": {"query": "incident runbook"},
    },
    {
        "name": "add_note",
        "title": "Add a note",
        "risk": "write",
        "arguments": {"title": "Playground note", "body": "Added through LiteLLM"},
    },
    {
        "name": "delete_collection",
        "title": "Delete a collection",
        "risk": "destructive",
        "arguments": {"name": "runbooks"},
    },
]


def demo_user(user: User = Depends(current_user)) -> User:
    if not settings().demo_mode:
        raise HTTPException(404, "The Cerbos playground is available in demo mode only")
    return user


def policy_error(error: policy_store.PolicyError):
    return JSONResponse({"detail": error.message, **error.payload}, status_code=error.status)


# --- Catalog ------------------------------------------------------------------------------


def kind_actions() -> dict[str, list[str]]:
    """Actions per resource kind, read from the live policies so edits show up."""
    actions: dict[str, list[str]] = {}
    for path in sorted(Path(settings().policies_dir).glob("*.yaml")):
        if not policy_store.is_policy_file(path):
            continue
        try:
            policy = (yaml.safe_load(path.read_text()) or {}).get("resourcePolicy") or {}
        except (OSError, yaml.YAMLError, AttributeError):
            continue
        kind = policy.get("resource")
        for rule in policy.get("rules") or []:
            for action in rule.get("actions") or []:
                if action != "*" and action not in actions.setdefault(kind, []):
                    actions[kind].append(action)
    # "view" first reads most naturally in a decision matrix.
    return {kind: sorted(names, key=lambda a: a != "view") for kind, names in actions.items()}


def resources_for(db: Session, kind: str) -> list[tuple[dict, str]]:
    teams = {team.id: team for team in db.scalars(select(Team))}
    if kind == "asset":
        return [
            (
                asset_resource(a, teams[a.team_id].cost_editor_ids if a.team_id in teams else []),
                a.name,
            )
            for a in db.scalars(
                select(Asset).where(Asset.status != "archived").order_by(Asset.name)
            )
        ]
    if kind == "approval":
        return [
            (approval_resource(a), f"{a.title} ({a.status})")
            for a in db.scalars(select(Approval).order_by(Approval.created_at.desc()))
        ]
    if kind == "api_key":
        return [
            (key_resource(k), f"{k.name} ({k.status})")
            for k in db.scalars(select(ApiKey).order_by(ApiKey.created_at.desc()))
        ]
    if kind == "budget":
        return [
            (budget_resource(b), f"{b.name} · {b.scope}")
            for b in db.scalars(select(Budget).order_by(Budget.scope, Budget.name))
        ]
    if kind == "team":
        return [(team_resource(t), t.name) for t in sorted(teams.values(), key=lambda t: t.name)]
    if kind == "department":
        return [
            (department_resource(d), d.name)
            for d in db.scalars(select(Department).order_by(Department.name))
        ]
    if kind == "platform":
        return [(platform_resource(), "Workspace")]
    if kind == "model":
        return [
            (model_resource(m, DEFAULT_TRACE_TOKENS), f"{m} ({MODEL_TIERS[m]})") for m in MODELS
        ]
    if kind == "mcp_tool":
        return [(mcp_tool_resource(t), f"{t['title']} ({t['risk']})") for t in MCP_TOOLS]
    raise HTTPException(422, "Unknown resource kind")


def demo_key_principal(db: Session, owner_id: str) -> dict:
    """The principal LiteLLM's guard would see for this owner's demo key.

    Built from the demo key specification, so it works before any key is issued.
    """
    issued = demo.demo_keys(db).get(owner_id)
    if issued:
        return key_principal(issued)
    spec = next((s for s in demo.DEMO_KEYS if s["owner"] == owner_id), None)
    asset = db.get(Asset, spec["asset"]) if spec else None
    if not asset:
        raise HTTPException(404, "No demo key for this persona")
    return {
        "id": f"key:demo-{owner_id}",
        "roles": ["api_key"],
        "attr": {
            "owner_id": owner_id,
            "team_id": asset.team_id or "",
            "department_id": asset.department_id,
            "asset_id": asset.id,
        },
    }


@router.get("/playground/catalog")
def catalog(user: User = Depends(demo_user), db: Session = Depends(get_db)):
    actions = kind_actions()
    with_keys = demo.demo_keys(db)
    return {
        "personas": [dump(u) for u in db.scalars(select(User).order_by(User.name))],
        "options": {
            "roles": KNOWN_ROLES,
            "teams": [dump(t) for t in db.scalars(select(Team).order_by(Team.name))],
            "departments": [
                dump(d) for d in db.scalars(select(Department).order_by(Department.name))
            ],
        },
        "kinds": [
            {
                "kind": kind,
                "description": description,
                "actions": actions.get(kind, []),
                "resources": [
                    {"id": item["id"], "label": label, "attr": item["attr"]}
                    for item, label in resources_for(db, kind)
                ],
            }
            for kind, description in KINDS.items()
        ],
        "scenarios": SCENARIOS,
        "demo_keys": [
            {
                "owner": spec["owner"],
                "name": spec["name"],
                "team": spec["team"],
                "key_id": with_keys[spec["owner"]].id if spec["owner"] in with_keys else None,
                "principal": demo_key_principal(db, spec["owner"]),
            }
            for spec in demo.DEMO_KEYS
        ],
        "models": [{"id": m, "tier": MODEL_TIERS[m]} for m in MODELS],
        "mcp_tools": [{k: t[k] for k in ("name", "title", "risk")} for t in MCP_TOOLS],
    }


# --- What-if checks ----------------------------------------------------------------------


class PrincipalSpec(StrictModel):
    persona_id: str | None = None
    key_owner: str | None = None
    key_id: str | None = None
    roles: list[str] | None = None
    team_ids: list[str] | None = None
    admin_team_ids: list[str] | None = None
    department_ids: list[str] | None = None
    team_id: str | None = None  # Only for key principals.


class CheckRequest(StrictModel):
    principal: PrincipalSpec
    kind: str
    resource_ids: list[str] = Field(min_length=1, max_length=100)
    resource_overrides: dict[str, Any] = Field(default_factory=dict)
    actions: list[str] | None = None


def build_principal(db: Session, spec: PrincipalSpec) -> dict:
    if spec.key_owner or spec.key_id:
        if spec.key_id:
            key = db.get(ApiKey, spec.key_id)
            if not key:
                raise HTTPException(404, "Unknown API key")
            result = key_principal(key)
        else:
            result = demo_key_principal(db, spec.key_owner)
        if spec.team_id is not None:
            if spec.team_id and not db.get(Team, spec.team_id):
                raise HTTPException(422, "Unknown team")
            result["attr"]["team_id"] = spec.team_id
        return result
    persona = db.get(User, spec.persona_id or "")
    if not persona:
        raise HTTPException(404, "Unknown persona")
    team_ids = {t.id for t in db.scalars(select(Team))}
    department_ids = {d.id for d in db.scalars(select(Department))}

    def pick(values, current, allowed, label):
        if values is None:
            return list(current)
        unknown = [v for v in values if v not in allowed]
        if unknown:
            raise HTTPException(422, f"Unknown {label}: {', '.join(unknown)}")
        return list(dict.fromkeys(values))

    roles = pick(spec.roles, persona.roles, KNOWN_ROLES, "role")
    if not roles:
        raise HTTPException(
            422, "Choose at least one role: Cerbos needs a role to evaluate any request."
        )
    return principal_from(
        persona.id,
        roles,
        pick(spec.team_ids, persona.team_ids, team_ids, "team"),
        pick(spec.admin_team_ids, persona.admin_team_ids, team_ids, "team"),
        pick(spec.department_ids, persona.department_ids, department_ids, "operating unit"),
    )


def apply_overrides(item: dict, overrides: dict[str, Any]) -> dict:
    attr = dict(item["attr"])
    for name, value in overrides.items():
        if name not in attr:
            raise HTTPException(422, f"'{name}' is not an attribute of {item['kind']}")
        valid = isinstance(value, str | bool | int) or (
            isinstance(value, list) and all(isinstance(v, str) for v in value)
        )
        if not valid:
            raise HTTPException(422, f"Unsupported value for '{name}'")
        attr[name] = value
    return {**item, "attr": attr}


def run_check(db: Session, request: CheckRequest) -> dict:
    principal = build_principal(db, request.principal)
    available = {item["id"]: (item, label) for item, label in resources_for(db, request.kind)}
    missing = [rid for rid in request.resource_ids if rid not in available]
    if missing:
        raise HTTPException(404, f"Unknown {request.kind}: {', '.join(missing)}")
    actions = request.actions or kind_actions().get(request.kind, [])
    if not actions:
        raise HTTPException(422, "This resource kind has no actions in the live policies")
    items = [
        apply_overrides(available[rid][0], request.resource_overrides)
        for rid in request.resource_ids
    ]
    decisions = explain(principal, items, actions)
    return {
        "principal": principal,
        "kind": request.kind,
        "actions": actions,
        "results": [
            {
                "id": item["id"],
                "label": available[item["id"]][1],
                "attr": item["attr"],
                "decisions": decisions.get(item["id"], {}),
            }
            for item in items
        ],
    }


@router.post("/playground/check")
def check(body: CheckRequest, user: User = Depends(demo_user), db: Session = Depends(get_db)):
    return run_check(db, body)


# --- Policies -----------------------------------------------------------------------------


class PolicyUpdate(StrictModel):
    yaml: str = Field(min_length=1, max_length=60_000)
    base_sha: str = Field(min_length=64, max_length=64)


@router.get("/policies")
def list_policies(user: User = Depends(demo_user)):
    return policy_store.summary()


@router.get("/policies/{policy_id}")
def read_policy(policy_id: str, user: User = Depends(demo_user)):
    try:
        return policy_store.document(policy_id)
    except policy_store.PolicyError as error:
        return policy_error(error)


@router.put("/policies/{policy_id}")
def update_policy(
    policy_id: str,
    body: PolicyUpdate,
    user: User = Depends(demo_user),
    db: Session = Depends(get_db),
):
    try:
        result = policy_store.save(policy_id, body.yaml, body.base_sha)
    except policy_store.PolicyError as error:
        return policy_error(error)
    changed = sum(
        1
        for line in policy_store.diff(policy_id).splitlines()
        if line[:1] in "+-" and not line.startswith(("+++", "---"))
    )
    bus.emit(
        db,
        "policy.updated",
        user.id,
        f"{policy_id}.yaml",
        changed_lines_vs_shipped=changed,
        policy_tests_failed=result["tests"]["failed"],
    )
    db.commit()
    return {**result, "document": policy_store.document(policy_id)}


@router.post("/policies/reset")
def reset_policies(user: User = Depends(demo_user), db: Session = Depends(get_db)):
    try:
        seconds = policy_store.reset()
    except policy_store.PolicyError as error:
        return policy_error(error)
    bus.emit(db, "policy.reset", user.id, "policies")
    db.commit()
    return {"ok": True, "reload_seconds": round(seconds, 2)}


# --- LiteLLM: demo keys and request trace --------------------------------------------------


@router.post("/playground/demo-keys")
def create_demo_keys(user: User = Depends(demo_user)):
    keys = demo.ensure_demo_keys(user.id)
    return {"keys": {owner: dump(key) for owner, key in keys.items()}}


def demo_key(owner: str, actor_id: str) -> tuple[ApiKey, str]:
    """The owner's demo key and its secret, issuing the demo keys first if needed."""
    from .db import SessionLocal

    if owner not in {spec["owner"] for spec in demo.DEMO_KEYS}:
        raise HTTPException(404, "No demo key for this persona")
    with SessionLocal() as db:
        key = demo.demo_keys(db).get(owner)
    if not key:
        key = demo.ensure_demo_keys(actor_id).get(owner)
    if not key:
        raise HTTPException(409, "The demo keys could not be issued; check that LiteLLM is running")
    return key, cipher().decrypt(key.encrypted_token.encode()).decode()


class TraceRequest(StrictModel):
    owner: str
    model: Literal["governed-demo", "governed-premium"]
    max_tokens: int = Field(default=DEFAULT_TRACE_TOKENS, ge=1, le=2048)
    path: Literal["gateway", "direct"] = "gateway"
    data_classification: Literal["public", "internal", "confidential"] = "internal"


def _outcome(status: int) -> str:
    return "deny" if status in (401, 403, 429) else "error"


def _summary(result: dict, completion: Completion, steps: list[dict]) -> dict:
    """Headline facts for the pipeline view: requested vs answering model, obligations."""
    litellm = next((s for s in steps if "inside LiteLLM" in s["name"]), {})
    provider = next((s for s in steps if s["name"] == "Provider"), {})
    return {
        **result,
        "requested_model": completion.model,
        "answered_model": provider.get("model"),
        "obligations": litellm.get("obligations") or {},
        "litellm_rule": litellm.get("rule"),
        "litellm_reason": litellm.get("reason"),
    }


@router.post("/playground/request")
def trace_request(body: TraceRequest, user: User = Depends(demo_user)):
    key, token = demo_key(body.owner, user.id)
    completion = Completion(
        model=body.model,
        messages=[{"role": "user", "content": "Summarize how this request is governed."}],
        max_tokens=body.max_tokens,
        data_classification=body.data_classification,
    )
    if body.path == "direct":
        steps, result = direct_to_litellm(token, completion, key_principal(key))
        return _summary(result, completion, steps)
    steps: list[dict] = []
    try:
        response = complete(token, completion, f"playground-{uuid.uuid4()}", steps)
    except HTTPException as error:
        result = {
            "outcome": _outcome(error.status_code),
            "http_status": error.status_code,
            "message": error.detail,
            "steps": steps,
        }
        return _summary(result, completion, steps)
    result = {
        "outcome": "allow",
        "http_status": 200,
        "message": "Answered through the governed gateway.",
        "steps": steps,
        "reply": response["choices"][0]["message"]["content"],
    }
    return _summary(result, completion, steps)


def direct_to_litellm(token: str, completion: Completion, guard_principal: dict):
    """Call LiteLLM directly with the key, skipping the gateway, to show Cerbos still applies."""
    steps = [
        {
            "name": "Gateway bypassed",
            "status": "skipped",
            "detail": "No gateway authorization and no budget reservation: the key is sent "
            "straight to LiteLLM, as a client inside the network could.",
        }
    ]
    name = "Cerbos inside LiteLLM: may this key invoke this model?"
    detail = (
        f"principal {guard_principal['id']} · resource model:{completion.model}"
        f" · max_tokens {completion.max_tokens} · {completion.data_classification} data"
    )
    try:
        result, headers = forward_completion(token, completion)
        model_used = answered_model(result, headers, completion.model)
    except httpx.HTTPStatusError as error:
        rejection = guard_rejection(error)
        if rejection:
            steps.append(
                {
                    "name": name,
                    "status": "deny",
                    "rule": rejection["rule"],
                    "reason": rejection["reason"],
                    "detail": detail,
                }
            )
            return steps, {
                "outcome": "deny",
                "http_status": rejection["status"],
                "message": f"Cerbos inside LiteLLM denied this call: {rejection['reason']}",
                "steps": steps,
            }
        steps.append({"name": "LiteLLM", "status": "error", "reason": "LiteLLM returned an error."})
        return steps, {
            "outcome": "error",
            "http_status": error.response.status_code,
            "message": "LiteLLM rejected the call for a reason other than Cerbos.",
            "steps": steps,
        }
    except (httpx.HTTPError, ValueError):
        steps.append({"name": "LiteLLM", "status": "error", "reason": "LiteLLM is unreachable."})
        return steps, {
            "outcome": "error",
            "http_status": 502,
            "message": "LiteLLM is unreachable.",
            "steps": steps,
        }
    decision = cerbos_headers(headers)
    steps.append(
        {
            "name": name,
            "status": "allow",
            "rule": decision["rule"],
            "reason": decision["reason"],
            "obligations": decision["obligations"],
            "detail": detail,
        }
    )
    steps.append(
        {
            "name": "Provider",
            "status": "ok",
            "model": model_used,
            "detail": f"Answered by {model_used}.",
        }
    )
    return steps, {
        "outcome": "allow",
        "http_status": 200,
        "message": "LiteLLM answered directly. Cerbos still decided, but no gateway budget applied.",
        "steps": steps,
        "reply": result["choices"][0]["message"]["content"],
        "headers": {k: v for k, v in headers.items() if k.startswith("x-cerbos")},
    }


# --- LiteLLM: model catalog and MCP tools ---------------------------------------------------


class OwnerRequest(StrictModel):
    owner: str


@router.post("/playground/model-catalog")
def model_catalog(body: OwnerRequest, user: User = Depends(demo_user)):
    """GET /v1/models as this key sees it: LiteLLM filters the list through Cerbos."""
    key, token = demo_key(body.owner, user.id)
    try:
        with httpx.Client(timeout=15) as client:
            response = client.get(
                f"{settings().litellm_url}/v1/models", headers={"Authorization": f"Bearer {token}"}
            )
            response.raise_for_status()
            visible = [m["id"] for m in response.json().get("data", [])]
    except (httpx.HTTPError, ValueError, KeyError):
        raise HTTPException(502, "LiteLLM did not return its model list") from None
    reasons = explain(
        key_principal(key),
        [model_resource(m, 1, "public") for m in MODELS],
        ["list"],
    )
    return {
        "owner": body.owner,
        "visible": visible,
        "models": [
            {"id": m, "tier": MODEL_TIERS[m], "visible": m in visible, **reasons[m]["list"]}
            for m in MODELS
        ],
    }


class ToolRequest(StrictModel):
    owner: str
    tool: Literal["search_docs", "add_note", "delete_collection"]


def _mcp_server_id(client: httpx.Client, token: str) -> str:
    response = client.get(
        f"{settings().litellm_url}/mcp-rest/tools/list",
        headers={"Authorization": f"Bearer {token}"},
    )
    response.raise_for_status()
    tools = response.json().get("tools") or []
    if not tools:
        raise HTTPException(502, "LiteLLM lists no MCP tools for this key")
    return tools[0]["mcp_info"]["server_id"]


@router.post("/playground/mcp")
def call_mcp_tool(body: ToolRequest, user: User = Depends(demo_user)):
    """Call a tool on the knowledge MCP server through LiteLLM's MCP gateway."""
    key, token = demo_key(body.owner, user.id)
    tool = next(t for t in MCP_TOOLS if t["name"] == body.tool)
    try:
        with httpx.Client(timeout=30) as client:
            server_id = _mcp_server_id(client, token)
            response = client.post(
                f"{settings().litellm_url}/mcp-rest/tools/call",
                headers={"Authorization": f"Bearer {token}"},
                json={"server_id": server_id, "name": tool["name"], "arguments": tool["arguments"]},
            )
            response.raise_for_status()
            payload = response.json()
    except httpx.HTTPStatusError as error:
        rejection = guard_rejection(error) or _detail_rejection(error)
        if rejection:
            return {"owner": body.owner, "tool": body.tool, "effect": "deny", **rejection}
        raise HTTPException(
            502, "LiteLLM's MCP gateway failed for a reason other than Cerbos"
        ) from None
    except (httpx.HTTPError, ValueError, KeyError):
        raise HTTPException(502, "LiteLLM's MCP gateway is unreachable") from None
    decision = explain(key_principal(key), [mcp_tool_resource(tool)], ["call"])[
        f"knowledge/{tool['name']}"
    ]["call"]
    text = " ".join(c.get("text", "") for c in payload.get("content") or [] if isinstance(c, dict))
    return {
        "owner": body.owner,
        "tool": body.tool,
        "effect": "allow",
        "rule": decision["rule"],
        "reason": decision["reason"],
        "result": text[:400],
    }


def _detail_rejection(error: httpx.HTTPStatusError) -> dict | None:
    """The MCP REST endpoint returns the guard's JSON under "detail" instead of "error"."""
    try:
        decision = json.loads(error.response.json()["detail"])
    except (ValueError, KeyError, TypeError):
        return None
    if not isinstance(decision, dict) or decision.get("marker") != "cerbos_guard":
        return None
    return {
        "status": error.response.status_code,
        "rule": decision.get("rule"),
        "reason": str(decision.get("reason") or ""),
        "resource": str(decision.get("resource") or ""),
    }


def mcp_tool_resource(tool: dict) -> dict:
    return {
        "kind": "mcp_tool",
        "id": f"knowledge/{tool['name']}",
        "attr": {
            "server": "knowledge",
            "tool": tool["name"],
            "risk": tool["risk"],
            "owner_team": "agents",
        },
    }


# --- AI traffic board: every situation, for every demo key, through LiteLLM ------------

SITUATIONS = [
    {
        "id": "standard",
        "group": "Model calls",
        "title": "Standard model, internal data",
        "request": {"model": "governed-demo", "max_tokens": 256, "data_classification": "internal"},
    },
    {
        "id": "premium",
        "group": "Model calls",
        "title": "Premium model, 256 tokens",
        "request": {
            "model": "governed-premium",
            "max_tokens": 256,
            "data_classification": "internal",
        },
    },
    {
        "id": "premium-long",
        "group": "Model calls",
        "title": "Premium model, 1024 tokens",
        "request": {
            "model": "governed-premium",
            "max_tokens": 1024,
            "data_classification": "internal",
        },
    },
    {
        "id": "confidential",
        "group": "Model calls",
        "title": "Confidential data, premium model",
        "request": {
            "model": "governed-premium",
            "max_tokens": 256,
            "data_classification": "confidential",
        },
    },
    {
        "id": "bypass",
        "group": "Model calls",
        "title": "Confidential data, standard model, bypassing the gateway",
        "request": {
            "model": "governed-demo",
            "max_tokens": 256,
            "data_classification": "confidential",
            "path": "direct",
        },
    },
    {"id": "catalog", "group": "Model catalog", "title": "List models (GET /v1/models)"},
    {
        "id": "mcp-read",
        "group": "MCP tools",
        "title": "Search the knowledge base",
        "tool": "search_docs",
    },
    {"id": "mcp-write", "group": "MCP tools", "title": "Add a note", "tool": "add_note"},
    {
        "id": "mcp-destructive",
        "group": "MCP tools",
        "title": "Delete a collection",
        "tool": "delete_collection",
    },
]


def _model_cell(result: dict, requested_tokens: int) -> dict:
    obligations = result.get("obligations") or {}
    if result["outcome"] == "deny":
        denied = next((s for s in result["steps"] if s["status"] == "deny"), {})
        outcome, rule, reason = (
            "refused",
            denied.get("rule"),
            denied.get("reason", result["message"]),
        )
    elif result["outcome"] == "error":
        outcome, rule, reason = "error", None, result["message"]
    else:
        rule, reason = result.get("litellm_rule"), result.get("litellm_reason") or ""
        if obligations.get("model"):
            outcome = "downgraded"
        elif int(obligations.get("max_tokens") or requested_tokens) < requested_tokens:
            outcome = "capped"
        else:
            outcome = "answered"
    return {
        "outcome": outcome,
        "rule": rule,
        "reason": reason,
        "answered_model": result.get("answered_model"),
        "obligations": obligations,
        "steps": result.get("steps", []),
    }


def _traffic_cell(situation: dict, owner: str, user: User) -> dict:
    try:
        if "request" in situation:
            request = {"path": "gateway", **situation["request"]}
            result = trace_request(TraceRequest(owner=owner, **request), user)
            return _model_cell(result, request["max_tokens"])
        if situation["id"] == "catalog":
            result = model_catalog(OwnerRequest(owner=owner), user)
            premium = next(m for m in result["models"] if m["id"] == "governed-premium")
            return {
                "outcome": "listed" if premium["visible"] else "hidden",
                "rule": premium["rule"],
                "reason": premium["reason"],
                "visible": result["visible"],
            }
        result = call_mcp_tool(ToolRequest(owner=owner, tool=situation["tool"]), user)
        return {
            "outcome": "called" if result["effect"] == "allow" else "refused",
            "rule": result.get("rule"),
            "reason": result.get("reason", ""),
            "result": result.get("result"),
        }
    except HTTPException as error:
        return {"outcome": "error", "rule": None, "reason": str(error.detail)}


@router.post("/playground/traffic")
def traffic(user: User = Depends(demo_user)):
    """Run every situation for every demo key: real calls through the gateway and LiteLLM."""
    started = time.monotonic()
    demo.ensure_demo_keys(user.id)
    owners = [spec["owner"] for spec in demo.DEMO_KEYS]
    jobs = [(situation, owner) for situation in SITUATIONS for owner in owners]
    with ThreadPoolExecutor(max_workers=6) as pool:
        cells = list(pool.map(lambda job: _traffic_cell(job[0], job[1], user), jobs))
    matrix = {f"{s['id']}:{owner}": cell for (s, owner), cell in zip(jobs, cells, strict=True)}
    counts: dict[str, int] = {}
    for cell in cells:
        counts[cell["outcome"]] = counts.get(cell["outcome"], 0) + 1
    return {
        "keys": [{k: spec[k] for k in ("owner", "team", "name")} for spec in demo.DEMO_KEYS],
        "situations": [{k: s[k] for k in ("id", "group", "title")} for s in SITUATIONS],
        "cells": matrix,
        "counts": counts,
        "calls": len(cells),
        "seconds": round(time.monotonic() - started, 2),
    }


# --- Story: capability board and one-click policy changes ------------------------------


class BoardRequest(StrictModel):
    persona_id: str
    what_ifs: list[str] = Field(default_factory=list, max_length=10)


@router.post("/playground/board")
def board(body: BoardRequest, user: User = Depends(demo_user), db: Session = Depends(get_db)):
    persona = db.get(User, body.persona_id)
    if not persona:
        raise HTTPException(404, "Unknown persona")
    known = {w["id"] for w in story.WHAT_IFS.get(persona.id, [])}
    unknown = [w for w in body.what_ifs if w not in known]
    if unknown:
        raise HTTPException(422, f"Unknown what-if for {persona.name}: {', '.join(unknown)}")
    return story.capability_board(db, persona, set(body.what_ifs))


def preset_states():
    texts = {}
    states = []
    for preset in story.PRESETS:
        if preset["policy"] not in texts:
            texts[preset["policy"]] = policy_store.read_live(preset["policy"])
        text = texts[preset["policy"]]
        states.append(
            {
                **{k: preset[k] for k in ("id", "title", "effect", "policy", "affects")},
                "on": preset["replace"] in text,
                "available": preset["replace"] in text or preset["find"] in text,
            }
        )
    return states


@router.get("/playground/presets")
def presets(user: User = Depends(demo_user)):
    return preset_states()


class PresetToggle(StrictModel):
    on: bool


@router.put("/playground/presets/{preset_id}")
def toggle_preset(
    preset_id: str,
    body: PresetToggle,
    user: User = Depends(demo_user),
    db: Session = Depends(get_db),
):
    preset = story.PRESETS_BY_ID.get(preset_id)
    if not preset:
        raise HTTPException(404, "Unknown policy change")
    document = policy_store.document(preset["policy"])
    source, target = (
        (preset["find"], preset["replace"]) if body.on else (preset["replace"], preset["find"])
    )
    if target in document["yaml"] and source not in document["yaml"]:
        return {"changed": False, "presets": preset_states()}
    if source not in document["yaml"]:
        raise HTTPException(
            409,
            "This policy was edited by hand, so the change cannot be applied. Reset policies first.",
        )
    try:
        result = policy_store.save(
            preset["policy"], document["yaml"].replace(source, target, 1), document["sha"]
        )
    except policy_store.PolicyError as error:
        return policy_error(error)
    bus.emit(
        db,
        "policy.updated",
        user.id,
        f"{preset['policy']}.yaml",
        change=preset["title"],
        enabled=body.on,
        policy_tests_failed=result["tests"]["failed"],
    )
    db.commit()
    return {"changed": True, **result, "presets": preset_states()}


# --- Demo reset ---------------------------------------------------------------------------


@router.post("/demo/reset")
def reset_demo(user: User = Depends(demo_user), db: Session = Depends(get_db)):
    # Release this request's own read locks first: TRUNCATE needs exclusive locks and
    # would otherwise wait forever on the session that loaded the signed-in user.
    db.rollback()
    db.close()
    try:
        demo.reset_workspace()
    except policy_store.PolicyError as error:
        return policy_error(error)
    return {"ok": True}
