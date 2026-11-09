"""Idempotent sample workspace. Enabled only in explicit DEMO_MODE."""

from datetime import timedelta

from sqlalchemy import select

from .config import settings
from .db import SessionLocal
from .models import Approval, Asset, Budget, Department, Event, Team, User, now


def seed():
    if not settings().demo_mode:
        return
    with SessionLocal.begin() as db:
        # Database advisory lock prevents concurrent API workers seeding twice.
        from sqlalchemy import text

        db.execute(text("SELECT pg_advisory_xact_lock(918271)"))
        if db.scalar(select(User.id).limit(1)):
            return
        departments = [
            ("technology", "Technology", "Building the systems that move us forward."),
            ("people", "Human Resources", "Thoughtful tools for our people."),
            ("operations", "Operations", "Keeping the organization running."),
        ]
        for id, name, description in departments:
            db.add(Department(id=id, name=name, description=description))
        db.flush()
        teams = [
            ("platform", "Platform Engineering", "technology", ["alex"]),
            ("agents", "Agents & Automation", "technology", []),
            ("infrastructure", "Infrastructure", "technology", []),
            ("people-ops", "People Operations", "people", []),
            ("business-ops", "Business Operations", "operations", []),
        ]
        for id, name, department, editors in teams:
            db.add(Team(id=id, name=name, department_id=department, cost_editor_ids=editors))
        users = [
            ("maya", "Maya Chen", ["viewer"], ["platform"], [], ["technology"]),
            ("alex", "Alex Rivera", ["developer"], ["platform"], [], ["technology"]),
            (
                "morgan",
                "Morgan Ellis",
                ["developer_admin"],
                ["platform", "agents"],
                ["platform", "agents"],
                ["technology"],
            ),
            ("jordan", "Jordan Lee", ["cost_center_admin"], [], [], ["technology"]),
            (
                "sam",
                "Sam Taylor",
                ["developer", "api_key_approver"],
                ["agents"],
                [],
                ["technology"],
            ),
            ("avery", "Avery Brooks", ["executive_admin"], [], [], []),
            ("riley", "Riley Park", ["developer"], ["people-ops"], [], ["people"]),
            ("casey", "Casey Reed", ["cost_center_admin"], [], [], ["people"]),
            ("quinn", "Quinn Davis", ["finance_admin"], [], [], []),
        ]
        for id, name, roles, team_ids, admin_teams, depts in users:
            db.add(
                User(
                    id=id,
                    name=name,
                    email=f"{id}@example.test",
                    roles=roles,
                    team_ids=team_ids,
                    admin_team_ids=admin_teams,
                    department_ids=depts,
                )
            )
        db.flush()
        specs = [
            (
                "atlas",
                "Atlas research agent",
                "agent",
                "Research, synthesize, and surface the information your team needs.",
                "alex",
                "platform",
                "global",
                "active",
                ["Research", "Knowledge"],
                1200,
                432.80,
            ),
            (
                "code-review",
                "Code review copilot",
                "agent",
                "A second pair of eyes for pull requests, security, and code quality.",
                "morgan",
                "platform",
                "team",
                "active",
                ["Engineering"],
                800,
                215.60,
            ),
            (
                "insights",
                "Customer insights",
                "agent",
                "Turn customer feedback into patterns and actionable insights.",
                "sam",
                "agents",
                "global",
                "active",
                ["Analytics"],
                1500,
                682.40,
            ),
            (
                "incident",
                "Incident responder",
                "agent",
                "Summarize incidents and suggest the next investigative step.",
                "morgan",
                "agents",
                "team",
                "active",
                ["Operations"],
                1000,
                354.20,
            ),
            (
                "people-assistant",
                "People assistant",
                "agent",
                "Answers to onboarding, benefits, and everyday people questions.",
                "riley",
                "people-ops",
                "global",
                "active",
                ["People"],
                900,
                246.50,
            ),
            (
                "release-notes",
                "Release notes assistant",
                "agent",
                "Draft clear release notes from merged pull requests.",
                "maya",
                "platform",
                "team",
                "pending",
                ["Engineering"],
                0,
                0,
            ),
            (
                "github-mcp",
                "GitHub connector",
                "mcp",
                "Connect agents to repositories, issues, and pull requests.",
                "alex",
                "platform",
                "global",
                "active",
                ["Developer tools"],
                0,
                0,
            ),
            (
                "postgres-mcp",
                "Postgres explorer",
                "mcp",
                "Read-only, schema-aware access to approved data sources.",
                "morgan",
                "platform",
                "team",
                "active",
                ["Data"],
                0,
                0,
            ),
            (
                "knowledge-mcp",
                "Knowledge base",
                "mcp",
                "Search and retrieve the team's shared documentation.",
                "sam",
                "agents",
                "global",
                "active",
                ["Knowledge"],
                0,
                0,
            ),
            (
                "doc-skill",
                "Document analysis",
                "skill",
                "Extract structured findings and citations from long documents.",
                "sam",
                "agents",
                "global",
                "active",
                ["Research"],
                0,
                0,
            ),
            (
                "pii-skill",
                "PII redaction",
                "skill",
                "Identify and redact sensitive personal information before sharing.",
                "alex",
                "platform",
                "global",
                "active",
                ["Security"],
                0,
                0,
            ),
            (
                "writing-skill",
                "Brand voice",
                "skill",
                "Apply consistent tone and editorial guidelines to generated content.",
                "riley",
                "people-ops",
                "global",
                "active",
                ["Content"],
                0,
                0,
            ),
        ]
        team_spend = {id: 0 for id, *_ in teams}
        for index, (
            id,
            name,
            kind,
            description,
            owner,
            team,
            visibility,
            status,
            tags,
            cap,
            spend,
        ) in enumerate(specs):
            dept = next(t[2] for t in teams if t[0] == team)
            at = now() - timedelta(days=12 - index, hours=index)
            db.add(
                Asset(
                    id=id,
                    name=name,
                    description=description,
                    kind=kind,
                    owner_id=owner,
                    team_id=team,
                    department_id=dept,
                    visibility=visibility,
                    status=status,
                    tags=tags,
                    endpoint=f"https://{id}.example.test" if kind == "mcp" else "",
                    model="governed-demo",
                    created_at=at,
                )
            )
            spent = round(spend * 1_000_000)
            team_spend[team] += spent
            db.add(
                Budget(
                    id=f"asset:{id}",
                    name=name,
                    scope="asset",
                    department_id=dept,
                    team_id=team,
                    limit_micros=cap * 1_000_000,
                    spent_micros=spent,
                )
            )
            db.add(
                Event(
                    type="asset.submitted" if status == "pending" else "asset.registered",
                    actor_id=owner,
                    department_id=dept,
                    team_id=team,
                    resource_id=id,
                    detail={"name": name, "sample_data": True},
                    created_at=at,
                )
            )
        dept_spend = {
            id: sum(team_spend[t[0]] for t in teams if t[2] == id) for id, *_ in departments
        }
        db.add(
            Budget(
                id="organization",
                name="Organization",
                scope="organization",
                limit_micros=25000 * 1_000_000,
                spent_micros=sum(dept_spend.values()),
            )
        )
        for id, name, _ in departments:
            db.add(
                Budget(
                    id=f"department:{id}",
                    name=name,
                    scope="department",
                    department_id=id,
                    limit_micros={"technology": 15000, "people": 6000, "operations": 4000}[id]
                    * 1_000_000,
                    spent_micros=dept_spend[id],
                )
            )
        for id, name, dept, _ in teams:
            db.add(
                Budget(
                    id=f"team:{id}",
                    name=name,
                    scope="team",
                    department_id=dept,
                    team_id=id,
                    limit_micros=5000 * 1_000_000
                    if dept == "technology"
                    else (6000 if dept == "people" else 4000) * 1_000_000,
                    spent_micros=team_spend[id],
                )
            )
        db.flush()
        db.add_all(
            [
                Approval(
                    id="request-release",
                    kind="asset",
                    title="Register Release notes assistant",
                    resource_id="release-notes",
                    department_id="technology",
                    team_id="platform",
                    requester_id="maya",
                    payload={"version": 1, "budget": "300"},
                    reason="Automate release notes for our weekly platform releases.",
                    created_at=now() - timedelta(hours=2),
                ),
                Approval(
                    id="request-atlas-budget",
                    kind="budget",
                    title="Budget for Atlas research agent",
                    resource_id="atlas",
                    department_id="technology",
                    team_id="platform",
                    requester_id="morgan",
                    payload={"budget": "1600", "previous_micros": 1200000000},
                    reason="Expand the research pilot to two additional product squads.",
                    created_at=now() - timedelta(hours=5),
                ),
                Approval(
                    id="request-atlas-key",
                    kind="key",
                    title="Research workspace · development",
                    resource_id="atlas",
                    department_id="technology",
                    team_id="platform",
                    requester_id="alex",
                    payload={
                        "asset_id": "atlas",
                        "name": "Research workspace · development",
                        "budget": "50",
                        "rpm": 30,
                        "tpm": 20000,
                        "days": 30,
                        "reason": "Connect the research workspace to our approved Atlas agent.",
                    },
                    reason="Connect the research workspace to our approved Atlas agent.",
                    created_at=now() - timedelta(hours=1),
                ),
                Approval(
                    id="request-people-budget",
                    kind="budget",
                    title="Budget for People assistant",
                    resource_id="people-assistant",
                    department_id="people",
                    team_id="people-ops",
                    requester_id="riley",
                    payload={"budget": "1200", "previous_micros": 900000000},
                    reason="Support the upcoming onboarding cohort.",
                    status="approved",
                    reviewer_id="casey",
                    review_note="Approved for the onboarding pilot.",
                    decided_at=now() - timedelta(days=1),
                    created_at=now() - timedelta(days=2),
                ),
            ]
        )
        # This historical request is an imported sample, not a pending authorization.
        db.get(Budget, "asset:people-assistant").limit_micros = 1200000000
    print("Sample workspace is ready.")


if __name__ == "__main__":
    seed()
