"""Guided Cerbos scenarios for the dashboard playground.

Each scenario is a short story plus one or more checks. A check is exactly what the
Explore tab can do by hand: pick a persona (optionally changing their roles, teams or
departments), pick resources (optionally changing attributes), and ask Cerbos about
actions. `expect` is what the shipped policies decide; tests/test_scenarios.py proves it.

Attributes that the demo itself can change (such as an approval's status after someone
decides it) are pinned with `resource_overrides`, so a scenario reads the same however
the workspace has been used.
"""

PENDING = {"status": "pending"}

SCENARIOS = [
    {
        "id": "self-approval",
        "title": "Nobody approves their own request",
        "story": (
            "Sam is an API key approver and may approve Alex's key request. If Sam had "
            "filed the request, the same approval is blocked by a deny rule that applies "
            "to every role."
        ),
        "checks": [
            {
                "label": "Sam reviews Alex's key request",
                "principal": {"persona_id": "sam"},
                "kind": "approval",
                "resource_ids": ["request-atlas-key"],
                "resource_overrides": PENDING,
                "actions": ["approve", "decline"],
                "expect": {"approve": "allow", "decline": "allow"},
            },
            {
                "label": "What if Sam had filed it?",
                "principal": {"persona_id": "sam"},
                "kind": "approval",
                "resource_ids": ["request-atlas-key"],
                "resource_overrides": {**PENDING, "requester_id": "sam"},
                "actions": ["approve", "decline"],
                "expect": {"approve": "deny", "decline": "deny"},
            },
        ],
    },
    {
        "id": "role-needs-team",
        "title": "A role alone is not enough",
        "story": (
            "The api_key_approver role only works while its holder is in the Agents team. "
            "Move Sam to the Platform team and the same role grants nothing. Cerbos "
            "combines roles with live attributes instead of hard-coding who may do what."
        ),
        "checks": [
            {
                "label": "Sam, in the Agents team",
                "principal": {"persona_id": "sam"},
                "kind": "approval",
                "resource_ids": ["request-atlas-key"],
                "resource_overrides": PENDING,
                "actions": ["view", "approve"],
                "expect": {"view": "allow", "approve": "allow"},
            },
            {
                "label": "Sam, moved to Platform",
                "principal": {"persona_id": "sam", "team_ids": ["platform"]},
                "kind": "approval",
                "resource_ids": ["request-atlas-key"],
                "resource_overrides": PENDING,
                "actions": ["view", "approve"],
                "expect": {"view": "deny", "approve": "deny"},
            },
        ],
    },
    {
        "id": "department-isolation",
        "title": "Cost admins only see their own department",
        "story": (
            "Jordan administers Technology and Casey administers Human Resources. They hold "
            "the same role, but the department attribute decides what each can see and "
            "approve."
        ),
        "checks": [
            {
                "label": "Jordan (Technology)",
                "principal": {"persona_id": "jordan"},
                "kind": "approval",
                "resource_ids": ["request-atlas-budget"],
                "resource_overrides": PENDING,
                "actions": ["view", "approve"],
                "expect": {"view": "allow", "approve": "allow"},
            },
            {
                "label": "Casey (Human Resources)",
                "principal": {"persona_id": "casey"},
                "kind": "approval",
                "resource_ids": ["request-atlas-budget"],
                "resource_overrides": PENDING,
                "actions": ["view", "approve"],
                "expect": {"view": "deny", "approve": "deny"},
            },
        ],
    },
    {
        "id": "personal-vs-team",
        "title": "Owning a team asset does not mean you may delete it",
        "story": (
            "Alex owns Atlas, but Atlas belongs to the Platform team, so only a team "
            "administrator such as Morgan may delete it. Make Atlas a personal asset and "
            "Alex may delete it."
        ),
        "checks": [
            {
                "label": "Alex, owner of the team asset",
                "principal": {"persona_id": "alex"},
                "kind": "asset",
                "resource_ids": ["atlas"],
                "actions": ["edit", "delete"],
                "expect": {"edit": "allow", "delete": "deny"},
            },
            {
                "label": "Morgan, Platform team admin",
                "principal": {"persona_id": "morgan"},
                "kind": "asset",
                "resource_ids": ["atlas"],
                "actions": ["edit", "delete"],
                "expect": {"edit": "allow", "delete": "allow"},
            },
            {
                "label": "Alex, if Atlas were personal",
                "principal": {"persona_id": "alex"},
                "kind": "asset",
                "resource_ids": ["atlas"],
                "resource_overrides": {"team_id": ""},
                "actions": ["edit", "delete"],
                "expect": {"edit": "allow", "delete": "allow"},
            },
        ],
    },
    {
        "id": "executive-read-only",
        "title": "Executives see everything and change nothing",
        "story": (
            "Avery can view every asset and budget in the organization, but explicit deny "
            "rules stop executives from editing, deleting or using assets and from "
            "changing spending caps."
        ),
        "checks": [
            {
                "label": "Avery on the Atlas agent",
                "principal": {"persona_id": "avery"},
                "kind": "asset",
                "resource_ids": ["atlas"],
                "actions": ["view", "edit", "delete", "use"],
                "expect": {"view": "allow", "edit": "deny", "delete": "deny", "use": "deny"},
            },
            {
                "label": "Avery on the Platform team budget",
                "principal": {"persona_id": "avery"},
                "kind": "budget",
                "resource_ids": ["team:platform"],
                "actions": ["view", "edit"],
                "expect": {"view": "allow", "edit": "deny"},
            },
        ],
    },
    {
        "id": "delegation",
        "title": "Budget rights are delegated person by person",
        "story": (
            "Alex was delegated the right to propose Atlas budget changes; Maya, in the "
            "same team, was not. Add Maya to the team's cost editors and Maya gains exactly "
            "that one right."
        ),
        "checks": [
            {
                "label": "Alex (delegated)",
                "principal": {"persona_id": "alex"},
                "kind": "asset",
                "resource_ids": ["atlas"],
                "resource_overrides": {"cost_editor_ids": ["alex"]},
                "actions": ["request_budget"],
                "expect": {"request_budget": "allow"},
            },
            {
                "label": "Maya (not delegated)",
                "principal": {"persona_id": "maya"},
                "kind": "asset",
                "resource_ids": ["atlas"],
                "resource_overrides": {"cost_editor_ids": ["alex"]},
                "actions": ["request_budget"],
                "expect": {"request_budget": "deny"},
            },
            {
                "label": "Maya, after delegation",
                "principal": {"persona_id": "maya"},
                "kind": "asset",
                "resource_ids": ["atlas"],
                "resource_overrides": {"cost_editor_ids": ["alex", "maya"]},
                "actions": ["request_budget"],
                "expect": {"request_budget": "allow"},
            },
        ],
    },
    {
        "id": "litellm-premium",
        "title": "Cerbos inside LiteLLM: allow, deny, or allow with conditions",
        "story": (
            "LiteLLM asks Cerbos before every model call. Alex's Platform key asking for the "
            "premium model is not refused: Cerbos allows it with an obligation, and LiteLLM "
            "downgrades it to the standard model. Sam's Agents key gets premium, capped at 512 "
            "tokens. Confidential data is refused on the standard model, even when the "
            "gateway is bypassed."
        ),
        "trace": [
            {
                "label": "Alex · premium · 256 tokens",
                "owner": "alex",
                "model": "governed-premium",
                "max_tokens": 256,
                "path": "gateway",
                "expect": "allow",
            },
            {
                "label": "Sam · premium · 1024 tokens",
                "owner": "sam",
                "model": "governed-premium",
                "max_tokens": 1024,
                "path": "gateway",
                "expect": "allow",
            },
            {
                "label": "Alex · standard · confidential data",
                "owner": "alex",
                "model": "governed-demo",
                "max_tokens": 256,
                "path": "gateway",
                "expect": "deny",
                "data_classification": "confidential",
            },
            {
                "label": "Alex · confidential · bypassing the gateway",
                "owner": "alex",
                "model": "governed-demo",
                "max_tokens": 256,
                "path": "direct",
                "expect": "deny",
                "data_classification": "confidential",
            },
        ],
        "checks": [
            {
                "label": "Alex's key (Platform)",
                "principal": {"key_owner": "alex"},
                "kind": "model",
                "resource_ids": ["governed-demo", "governed-premium"],
                "resource_overrides": {"max_tokens": 256},
                "actions": ["list", "invoke"],
                "expect_by_resource": {
                    "governed-demo": {"list": "allow", "invoke": "allow"},
                    "governed-premium": {"list": "deny", "invoke": "allow"},
                },
            },
            {
                "label": "Sam's key (Agents)",
                "principal": {"key_owner": "sam"},
                "kind": "model",
                "resource_ids": ["governed-demo", "governed-premium"],
                "resource_overrides": {"max_tokens": 256},
                "actions": ["list", "invoke"],
                "expect_by_resource": {
                    "governed-demo": {"list": "allow", "invoke": "allow"},
                    "governed-premium": {"list": "allow", "invoke": "allow"},
                },
            },
        ],
    },
    {
        "id": "edit-a-rule",
        "title": "Change a rule and every decision follows",
        "story": (
            "Policies are data, not code. Open model.yaml, add 'platform' to the "
            "premium_teams variable and save. Cerbos validates the change, runs the policy "
            "test suite (some tests now fail, as expected) and reloads within seconds. The "
            "premium model then appears in Alex's model catalog inside LiteLLM, with no "
            "redeploy. Reset policies afterwards."
        ),
        "policy_edit": {
            "policy": "model",
            "find": "premium_teams: \"['agents']\"",
            "replace": "premium_teams: \"['agents', 'platform']\"",
        },
        "checks": [
            {
                "label": "Premium in Alex's model catalog",
                "principal": {"key_owner": "alex"},
                "kind": "model",
                "resource_ids": ["governed-premium"],
                "actions": ["list"],
                "expect": {"list": "deny"},
                "expect_after_edit": {"list": "allow"},
            },
        ],
    },
]
