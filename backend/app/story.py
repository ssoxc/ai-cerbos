"""The content of the story-first Cerbos playground.

* CAPABILITIES: plain-language things a person might want to do, in three scopes
  (Technology, Human Resources, Organization). Each is one real Cerbos check against
  seeded data.
* WHAT_IFS: three hand-picked what-ifs per persona. Each names the Cerbos concept it
  demonstrates, describes the attribute change, and declares exactly which capabilities
  it flips (`flips`) or which decision it spotlights. Nothing is saved; Cerbos simply
  receives a different principal or resource.
* PRESETS: one-click policy changes, applied through the validated, tested and
  hot-reloaded path used by the YAML editor.

tests/test_story.py proves every declared flip and spotlight against the shipped
policies, so the stories told here cannot drift from what Cerbos decides.
"""

from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from .models import Approval, Asset, Budget, Department, Team, User
from .policy import (
    approval_resource,
    asset_resource,
    budget_resource,
    explain,
    platform_resource,
    principal_from,
    resource,
)

SCOPES = [
    {"id": "technology", "title": "Technology", "subtitle": "Atlas agent · Platform Engineering"},
    {
        "id": "people",
        "title": "Human Resources",
        "subtitle": "People assistant · People Operations",
    },
    {"id": "organization", "title": "Organization", "subtitle": "Keys, units and the global cap"},
]


@dataclass(frozen=True)
class Capability:
    id: str
    scope: str
    label: str
    kind: str
    resource_id: str
    action: str
    # Attributes pinned so the story reads the same however the demo has been used.
    pin: dict = field(default_factory=dict)


PENDING = {"status": "pending"}
CAPABILITIES = [
    Capability("t-edit", "technology", "Edit the Atlas agent", "asset", "atlas", "edit"),
    Capability("t-delete", "technology", "Delete the Atlas agent", "asset", "atlas", "delete"),
    Capability(
        "t-key", "technology", "Request an API key for Atlas", "asset", "atlas", "request_key"
    ),
    Capability(
        "t-propose",
        "technology",
        "Propose a new budget for Atlas",
        "asset",
        "atlas",
        "request_budget",
    ),
    Capability(
        "t-approve-budget",
        "technology",
        "Approve the Atlas budget increase",
        "approval",
        "request-atlas-budget",
        "approve",
        PENDING,
    ),
    Capability(
        "t-approve-key",
        "technology",
        "Approve Alex's API key request",
        "approval",
        "request-atlas-key",
        "approve",
        PENDING,
    ),
    Capability(
        "t-cap",
        "technology",
        "Change Platform Engineering's spending cap",
        "budget",
        "team:platform",
        "edit",
    ),
    Capability(
        "h-edit", "people", "Edit the People assistant", "asset", "people-assistant", "edit"
    ),
    Capability(
        "h-delete", "people", "Delete the People assistant", "asset", "people-assistant", "delete"
    ),
    Capability(
        "h-propose",
        "people",
        "Propose a new budget for the People assistant",
        "asset",
        "people-assistant",
        "request_budget",
    ),
    Capability(
        "h-approve-budget",
        "people",
        "Approve the People assistant budget request",
        "approval",
        "request-people-budget",
        "approve",
        PENDING,
    ),
    Capability(
        "h-cap",
        "people",
        "Change People Operations' spending cap",
        "budget",
        "team:people-ops",
        "edit",
    ),
    Capability(
        "o-revoke", "organization", "Revoke Alex's Atlas API key", "key", "alex-atlas-key", "revoke"
    ),
    Capability(
        "o-unit",
        "organization",
        "Create a new operating unit",
        "platform",
        "workspace",
        "create_department",
    ),
    Capability(
        "o-org-cap",
        "organization",
        "Change the organization-wide spending cap",
        "budget",
        "organization",
        "edit",
    ),
]
CAPABILITY_IDS = {c.id for c in CAPABILITIES}

CONCEPTS = {
    "role": "Role",
    "team": "Team membership",
    "scoped-admin": "Scoped admin",
    "ownership": "Ownership",
    "delegation": "Delegation",
    "department": "Department scope",
    "separation": "Separation of duties",
    "self-approval": "Self-approval",
}


def what_if(id, concept, label, hint, change, flips=(), spotlight=None):
    return {
        "id": id,
        "concept": concept,
        "label": label,
        "hint": hint,
        "change": change,
        "flips": sorted(flips),
        "spotlight": spotlight,
    }


# change keys: set_/add_/remove_ + roles, teams, admin_teams, departments; delegate (an
# asset id: add the person to that team's budget editors); resource (attribute overrides,
# by resource id).
WHAT_IFS = {
    "maya": [
        what_if(
            "promote",
            "role",
            "Is promoted to developer",
            "A role change alone: team assets become editable and usable.",
            {"set_roles": ["developer"]},
            {"t-edit", "t-key"},
        ),
        what_if(
            "delegate",
            "delegation",
            "Is delegated Atlas budget rights",
            "Platform's admin adds Maya to the team's budget editors. Exactly one right appears.",
            {"delegate": "atlas"},
            {"t-propose"},
        ),
        what_if(
            "admin",
            "scoped-admin",
            "Becomes admin of Platform Engineering",
            "Admin power scoped to one team: everything about Atlas, nothing about HR.",
            {"set_roles": ["developer_admin"], "add_admin_teams": ["platform"]},
            {"t-edit", "t-delete", "t-key", "t-propose", "o-revoke"},
        ),
    ],
    "alex": [
        what_if(
            "leave-platform",
            "team",
            "Leaves Platform Engineering",
            "Team rights go, but Alex still owns Atlas, so editing stays allowed.",
            {"remove_teams": ["platform"]},
            {"t-key", "t-propose"},
            spotlight="t-edit",
        ),
        what_if(
            "personal",
            "ownership",
            "Atlas becomes a personal agent",
            "A resource change, not a person change: owners may delete personal assets.",
            {"resource": {"atlas": {"team_id": ""}}},
            {"t-delete", "t-propose"},
        ),
        what_if(
            "approver",
            "self-approval",
            "Becomes an API key approver in Agents",
            "Even with the role and the team, nobody approves their own request.",
            {"add_roles": ["api_key_approver"], "add_teams": ["agents"]},
            set(),
            spotlight="t-approve-key",
        ),
    ],
    "morgan": [
        what_if(
            "drop-admin",
            "scoped-admin",
            "Is no longer admin of Platform Engineering",
            "Still a member, no longer an admin: deleting, budgets and keys go.",
            {"remove_admin_teams": ["platform"]},
            {"t-delete", "t-propose", "o-revoke"},
        ),
        what_if(
            "move-hr",
            "department",
            "Moves to People Operations in HR",
            "Every Technology right disappears, and the HR team's agent becomes editable.",
            {"set_teams": ["people-ops"], "set_admin_teams": [], "set_departments": ["people"]},
            {"t-edit", "t-delete", "t-key", "t-propose", "o-revoke", "h-edit"},
        ),
        what_if(
            "cost-admin",
            "separation",
            "Is also made a Technology cost admin",
            "A finance role takes away every builder power, whatever else Morgan is.",
            {"add_roles": ["cost_center_admin"]},
            {"t-edit", "t-delete", "t-key", "t-propose", "o-revoke", "t-cap"},
        ),
    ],
    "jordan": [
        what_if(
            "cover-hr",
            "department",
            "Also covers Human Resources",
            "One more operating unit in scope: HR approvals and caps appear.",
            {"add_departments": ["people"]},
            {"h-approve-budget", "h-cap"},
        ),
        what_if(
            "move-hr",
            "department",
            "Moves to Human Resources",
            "Same role, different scope: Technology rights go, HR rights come.",
            {"set_departments": ["people"]},
            {"t-approve-budget", "t-cap", "h-approve-budget", "h-cap"},
        ),
        what_if(
            "developer",
            "separation",
            "Is also given a developer role",
            "Cerbos still refuses: cost admins never change assets, whatever other roles they hold.",
            {"add_roles": ["developer"], "add_teams": ["platform"]},
            set(),
            spotlight="t-edit",
        ),
    ],
    "sam": [
        what_if(
            "leave-agents",
            "team",
            "Leaves the Agents & Automation team",
            "The approver role only works inside Agents: key approvals and revocations go.",
            {"remove_teams": ["agents"]},
            {"t-approve-key", "o-revoke"},
        ),
        what_if(
            "filed",
            "self-approval",
            "Had filed Alex's key request",
            "A resource change: the requester becomes Sam, and self-approval is blocked.",
            {"resource": {"request-atlas-key": {"requester_id": "sam"}}},
            {"t-approve-key"},
        ),
        what_if(
            "join-platform",
            "team",
            "Joins Platform Engineering",
            "Team membership alone opens Atlas for editing and keys.",
            {"add_teams": ["platform"]},
            {"t-edit", "t-key"},
        ),
    ],
    "avery": [
        what_if(
            "developer",
            "separation",
            "Is also given a developer role",
            "Executives can never change assets, even with a builder role on top.",
            {"add_roles": ["developer"], "add_teams": ["platform"]},
            set(),
            spotlight="t-edit",
        ),
        what_if(
            "cost-admin",
            "role",
            "Steps down to Technology cost admin",
            "Approvals and caps in one department, but no more organization-wide powers.",
            {"set_roles": ["cost_center_admin"], "set_departments": ["technology"]},
            {"t-approve-budget", "t-cap", "o-unit"},
        ),
        what_if(
            "finance",
            "role",
            "Becomes finance admin instead",
            "Owns the organization cap, gives up creating operating units.",
            {"set_roles": ["finance_admin"]},
            {"o-org-cap", "o-unit"},
        ),
    ],
    "riley": [
        what_if(
            "admin",
            "scoped-admin",
            "Becomes admin of People Operations",
            "The same admin powers Morgan has in Technology, scoped to HR.",
            {"set_roles": ["developer_admin"], "add_admin_teams": ["people-ops"]},
            {"h-delete", "h-propose"},
        ),
        what_if(
            "delegate",
            "delegation",
            "Is delegated People assistant budget rights",
            "One right, granted by a team admin and revocable at any time.",
            {"delegate": "people-assistant"},
            {"h-propose"},
        ),
        what_if(
            "join-platform",
            "team",
            "Also joins Platform Engineering",
            "Atlas opens up, and Riley still edits the People assistant as its owner.",
            {"add_teams": ["platform"]},
            {"t-edit", "t-key"},
            spotlight="h-edit",
        ),
    ],
    "casey": [
        what_if(
            "cover-tech",
            "department",
            "Also covers Technology",
            "A second department: Atlas approvals and Platform's cap come into scope.",
            {"add_departments": ["technology"]},
            {"t-approve-budget", "t-cap"},
        ),
        what_if(
            "filed",
            "self-approval",
            "Had filed the People assistant budget request",
            "The requester cannot approve their own request, even as the department's admin.",
            {"resource": {"request-people-budget": {"requester_id": "casey"}}},
            {"h-approve-budget"},
        ),
        what_if(
            "move-tech",
            "department",
            "Moves to Technology",
            "Same role, different scope: every HR right moves to Technology.",
            {"set_departments": ["technology"]},
            {"t-approve-budget", "t-cap", "h-approve-budget", "h-cap"},
        ),
    ],
    "quinn": [
        what_if(
            "lose-finance",
            "role",
            "Loses the finance admin role",
            "Only finance admins change the organization-wide cap.",
            {"set_roles": ["viewer"]},
            {"o-org-cap"},
        ),
        what_if(
            "hr-cost-admin",
            "separation",
            "Is also made cost admin for HR",
            "HR's cap becomes editable, but finance admins still never decide requests.",
            {"add_roles": ["cost_center_admin"], "add_departments": ["people"]},
            {"h-cap"},
            spotlight="h-approve-budget",
        ),
        what_if(
            "executive",
            "separation",
            "Is also made an executive",
            "Gains creating units, loses the cap: executives never change caps.",
            {"add_roles": ["executive_admin"]},
            {"o-unit", "o-org-cap"},
        ),
    ],
}

PRESETS = [
    {
        "id": "platform-premium",
        "title": "Let Platform Engineering use the premium model",
        "effect": "Alex's premium requests stop being downgraded, and premium appears in Alex's model catalog.",
        "policy": "model",
        "find": "premium_teams: \"['agents']\"",
        "replace": "premium_teams: \"['agents', 'platform']\"",
        "affects": "litellm",
    },
    {
        "id": "hr-confidential",
        "title": "Let People Operations send confidential data to premium",
        "effect": "Riley's confidential HR prompts go to the zero-retention premium model instead of being refused.",
        "policy": "model",
        "find": "confidential_teams: \"['agents']\"",
        "replace": "confidential_teams: \"['agents', 'people-ops']\"",
        "affects": "litellm",
    },
    {
        "id": "raise-cap",
        "title": "Raise the premium token cap to 2048",
        "effect": "Cerbos stops capping Agents-team premium requests at 512 tokens.",
        "policy": "model",
        "find": 'premium_max_tokens: "512"',
        "replace": 'premium_max_tokens: "2048"',
        "affects": "litellm",
    },
    {
        "id": "all-teams-write",
        "title": "Let every team's keys add notes through MCP",
        "effect": "The add_note tool is no longer reserved for the team that owns the MCP server.",
        "policy": "mcp_tool",
        "find": "expr: R.attr.risk == 'write' && P.attr.team_id == R.attr.owner_team",
        # A trailing YAML comment keeps the "on" text distinct from the "off" text.
        "replace": "expr: R.attr.risk == 'write'  # any team may write",
        "affects": "litellm",
    },
    {
        "id": "cost-admins-keys",
        "title": "Let cost-center admins approve API keys",
        "effect": "Jordan can approve Alex's key request; Casey still cannot, because it is outside Casey's department.",
        "policy": "approval",
        "find": "request.resource.attr.kind in ['asset', 'budget']",
        "replace": "request.resource.attr.kind in ['asset', 'budget', 'key']",
        "affects": "people",
    },
]
PRESETS_BY_ID = {preset["id"]: preset for preset in PRESETS}


def _team_editors(db: Session, team_id: str | None) -> list[str]:
    team = db.get(Team, team_id) if team_id else None
    return list(team.cost_editor_ids) if team else []


def _resource(db: Session, capability: Capability, persona: User, change: dict) -> dict | None:
    if capability.kind == "asset":
        asset = db.get(Asset, capability.resource_id)
        if not asset:
            return None
        editors = _team_editors(db, asset.team_id)
        if change.get("delegate") == asset.id:
            editors = sorted({*editors, persona.id})
        item = asset_resource(asset, editors)
    elif capability.kind == "approval":
        approval = db.get(Approval, capability.resource_id)
        if not approval:
            return None
        item = approval_resource(approval)
    elif capability.kind == "budget":
        budget = db.get(Budget, capability.resource_id)
        if not budget:
            return None
        item = budget_resource(budget)
    elif capability.kind == "key":
        # Alex's Atlas key, as the api_key policy sees any key of the Platform team.
        item = resource(
            "api_key",
            capability.resource_id,
            owner_id="alex",
            department_id="technology",
            team_id="platform",
        )
    else:
        item = platform_resource()
    item["attr"].update(capability.pin)
    item["attr"].update((change.get("resource") or {}).get(capability.resource_id, {}))
    return item


def principal_with(persona: User, change: dict) -> dict:
    def apply(current, name):
        values = list(change.get(f"set_{name}", current))
        values += change.get(f"add_{name}", [])
        removed = set(change.get(f"remove_{name}", []))
        return list(dict.fromkeys(v for v in values if v not in removed))

    return principal_from(
        persona.id,
        apply(persona.roles, "roles"),
        apply(persona.team_ids, "teams"),
        apply(persona.admin_team_ids, "admin_teams"),
        apply(persona.department_ids, "departments"),
    )


def combined_change(persona_id: str, what_if_ids: set[str]) -> dict:
    """Merge the selected what-ifs of one persona into a single change."""
    merged: dict = {}
    for item in WHAT_IFS.get(persona_id, []):
        if item["id"] not in what_if_ids:
            continue
        for key, value in item["change"].items():
            if key == "resource":
                for rid, attrs in value.items():
                    merged.setdefault("resource", {}).setdefault(rid, {}).update(attrs)
            elif key.startswith("add_") or key.startswith("remove_"):
                merged[key] = [*merged.get(key, []), *value]
            else:
                merged[key] = value
    return merged


def decide(db: Session, persona: User, change: dict) -> dict[str, dict]:
    principal = principal_with(persona, change)
    decisions: dict[str, dict] = {}
    for capability in CAPABILITIES:
        item = _resource(db, capability, persona, change)
        if item is None:
            continue
        result = explain(principal, [item], [capability.action], source="playground").get(
            item["id"], {}
        )
        decisions[capability.id] = result.get(capability.action) or {
            "effect": "deny",
            "policy": "",
            "rule": None,
            "reason": "No rule matched, so Cerbos denies by default.",
        }
    return decisions


def _describe(db: Session, principal: dict) -> dict:
    teams = {t.id: t.name for t in db.query(Team)}
    departments = {d.id: d.name for d in db.query(Department)}
    attr = principal["attr"]
    return {
        "roles": principal["roles"],
        "teams": [teams.get(t, t) for t in attr["team_ids"]],
        "admin_teams": [teams.get(t, t) for t in attr["admin_team_ids"]],
        "departments": [departments.get(d, d) for d in attr["department_ids"]],
    }


def capability_board(db: Session, persona: User, selected: set[str]) -> dict:
    change = combined_change(persona.id, selected)
    baseline = decide(db, persona, {})
    current = decide(db, persona, change) if selected else baseline
    what_ifs = WHAT_IFS.get(persona.id, [])
    spotlights = [
        {"what_if": w["id"], "capability": w["spotlight"], **current[w["spotlight"]]}
        for w in what_ifs
        if w["id"] in selected and w["spotlight"] in current
    ]
    return {
        "persona": {"id": persona.id, "name": persona.name},
        "before": _describe(db, principal_with(persona, {})),
        "after": _describe(db, principal_with(persona, change)),
        "scopes": SCOPES,
        "concepts": CONCEPTS,
        "what_ifs": [
            {k: w[k] for k in ("id", "concept", "label", "hint", "flips", "spotlight")}
            | {"on": w["id"] in selected}
            for w in what_ifs
        ],
        "spotlights": spotlights,
        "capabilities": [
            {
                "id": c.id,
                "scope": c.scope,
                "label": c.label,
                **current[c.id],
                "was": baseline[c.id]["effect"],
                "changed": current[c.id]["effect"] != baseline[c.id]["effect"],
            }
            for c in CAPABILITIES
            if c.id in current
        ],
        "allowed": sum(1 for c in CAPABILITIES if current.get(c.id, {}).get("effect") == "allow"),
        "baseline_allowed": sum(
            1 for c in CAPABILITIES if baseline.get(c.id, {}).get("effect") == "allow"
        ),
        "total": len(current),
    }
