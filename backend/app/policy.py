import uuid
from functools import lru_cache
from pathlib import Path

import httpx
import yaml
from fastapi import HTTPException

from .config import settings
from .models import User

ASSET_ACTIONS = ["view", "edit", "delete", "request_budget", "request_key", "use"]
NO_MATCH_REASON = "No rule matched, so Cerbos denies by default."
BATCH = 50
# Cerbos records this header in its decision log (includeMetadataKeys in cerbos/config.yaml),
# so the metrics page can tell enforcement from lookups and simulations:
#   api        an action was attempted and allowed or refused (require)
#   gateway    the gateway checked an AI request
#   litellm    LiteLLM's Cerbos guard checked a model, catalog or MCP tool call
#   dashboard  the dashboard asked what a person may do, to show or hide controls
#   playground a what-if simulation; probe: the policy reload check
SOURCE_HEADER = "X-Ai-Spine-Source"


def principal(user: User):
    return principal_from(
        user.id, user.roles, user.team_ids, user.admin_team_ids, user.department_ids
    )


def principal_from(id, roles, team_ids, admin_team_ids, department_ids):
    return {
        "id": id,
        "roles": list(roles),
        "attr": {
            "team_ids": list(team_ids),
            "admin_team_ids": list(admin_team_ids),
            "department_ids": list(department_ids),
        },
    }


def resource(resource_kind, id, **attrs):
    return {"kind": resource_kind, "id": id, "attr": attrs}


def _post_checks(principal_dict, resources, actions, include_meta=False, source="dashboard"):
    """Yield Cerbos results for every resource, in batches. Fails closed with a 503."""
    try:
        with httpx.Client(timeout=8, headers={SOURCE_HEADER: source}) as client:
            for start in range(0, len(resources), BATCH):
                body = {
                    "requestId": str(uuid.uuid4()),
                    "principal": principal_dict,
                    "resources": [
                        {"resource": r, "actions": actions}
                        for r in resources[start : start + BATCH]
                    ],
                }
                if include_meta:
                    body["includeMeta"] = True
                response = client.post(f"{settings().cerbos_url}/api/check/resources", json=body)
                response.raise_for_status()
                yield from response.json()["results"]
    except (httpx.HTTPError, ValueError, KeyError):
        raise HTTPException(
            503, "Authorization service unavailable. Access is denied until Cerbos recovers."
        ) from None


def check_many(user: User, resources: list[dict], actions: list[str], source="dashboard"):
    if not resources:
        return {}
    return {
        item["resource"]["id"]: {
            action: item["actions"].get(action) == "EFFECT_ALLOW" for action in actions
        }
        for item in _post_checks(principal(user), resources, actions, source=source)
    }


def permissions(user, item, actions, source="dashboard"):
    return check_many(user, [item], actions, source=source).get(item["id"], {})


def require(user, item, action):
    """Enforce one attempted action. Cerbos logs it as source "api"."""
    if not permissions(user, item, [action], source="api").get(action):
        raise HTTPException(403, "Cerbos denied this action for your role and scope")


# --- Explanations -----------------------------------------------------------------------
# Every policy rule has a name and an output sentence. Cerbos returns the outputs of the
# rules that activated, tagged with policy, rule and action. The rule's own effect (read
# from the policy files) decides which activated rule explains the final decision.


@lru_cache(maxsize=64)
def _parse_policy(path: str, mtime_ns: int) -> tuple[str, dict[str, str]]:
    """(resource kind, {rule name: effect}) for one policy file, cached per file version."""
    try:
        document = yaml.safe_load(Path(path).read_text()) or {}
    except (OSError, yaml.YAMLError):
        return "", {}
    policy = document.get("resourcePolicy") if isinstance(document, dict) else None
    if not isinstance(policy, dict):
        return "", {}
    rules = policy.get("rules") or []
    return str(policy.get("resource", "")), {
        rule["name"]: rule.get("effect", "")
        for rule in rules
        if isinstance(rule, dict) and "name" in rule
    }


def rule_effects() -> dict[str, str]:
    """Map "<kind>#<rule-name>" to the rule's effect, from the live policy directory."""
    effects = {}
    for path in sorted(Path(settings().policies_dir).glob("*.yaml")):
        if path.name.endswith("_test.yaml"):
            continue
        try:
            kind, rules = _parse_policy(str(path), path.stat().st_mtime_ns)
        except OSError:
            continue
        for name, effect in rules.items():
            effects[f"{kind}#{name}"] = effect
    return effects


def decided_by(kind, action, effect, activated, effects=None):
    """The named rule behind one action's decision: (rule, reason, obligations).

    `activated` is Cerbos's list of rule outputs for the resource (from a check response or
    its decision log). Several rules can activate; the one whose own effect matches the
    final effect explains the decision.
    """
    effects = rule_effects() if effects is None else effects
    wanted = "EFFECT_ALLOW" if effect == "EFFECT_ALLOW" else "EFFECT_DENY"
    for entry in activated or []:
        if entry.get("action") != action:
            continue
        rule = entry.get("src", "").rsplit("#", 1)[-1]
        value = entry.get("val", "")
        obligations = {}
        # Some outputs are maps carrying their own effect (see model.yaml).
        if isinstance(value, dict):
            rule_effect = f"EFFECT_{str(value.get('effect', '')).upper()}"
            obligations = value.get("obligations") or {}
            value = value.get("reason", "")
        else:
            rule_effect = effects.get(f"{kind}#{rule}")
        if rule_effect == wanted:
            return rule, str(value), obligations if isinstance(obligations, dict) else {}
    return None, NO_MATCH_REASON, {}


def explain(principal_dict: dict, resources: list[dict], actions: list[str], source="dashboard"):
    """Decide like check_many, and also say which named rule decided and why."""
    if not resources:
        return {}
    effects = rule_effects()
    output = {}
    for item in _post_checks(principal_dict, resources, actions, include_meta=True, source=source):
        kind, rid = item["resource"]["kind"], item["resource"]["id"]
        meta = (item.get("meta") or {}).get("actions", {})
        decisions = {}
        for action in actions:
            effect = item["actions"].get(action, "EFFECT_DENY")
            rule, reason, _ = decided_by(kind, action, effect, item.get("outputs"), effects)
            decisions[action] = {
                "effect": "allow" if effect == "EFFECT_ALLOW" else "deny",
                "policy": (meta.get(action) or {}).get("matchedPolicy") or "",
                "rule": rule,
                "reason": reason,
            }
        output[rid] = decisions
    return output


# --- Resource builders -------------------------------------------------------------------
# One place defines the attributes Cerbos sees for each kind, for the app and the playground.


def asset_resource(asset, cost_editor_ids=None):
    return resource(
        "asset",
        asset.id,
        owner_id=asset.owner_id,
        team_id=asset.team_id or "",
        department_id=asset.department_id,
        visibility=asset.visibility,
        status=asset.status,
        kind=asset.kind,
        cost_editor_ids=cost_editor_ids or [],
    )


def approval_resource(approval):
    return resource(
        "approval",
        approval.id,
        requester_id=approval.requester_id,
        department_id=approval.department_id,
        team_id=approval.team_id or "",
        kind=approval.kind,
        status=approval.status,
    )


def key_resource(key):
    return resource(
        "api_key",
        key.id,
        owner_id=key.owner_id,
        department_id=key.department_id,
        team_id=key.team_id or "",
    )


def budget_resource(budget):
    return resource(
        "budget",
        budget.id,
        scope=budget.scope,
        department_id=budget.department_id,
        team_id=budget.team_id,
    )


def team_resource(team):
    return resource("team", team.id, department_id=team.department_id)


def department_resource(department):
    return resource("department", department.id)


def audit_resource(event):
    return resource(
        "audit",
        event.id,
        actor_id=event.actor_id,
        department_id=event.department_id,
        team_id=event.team_id,
    )


def platform_resource():
    return resource("platform", "workspace")
