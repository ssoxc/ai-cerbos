import asyncio
import contextlib
from contextlib import asynccontextmanager
from decimal import Decimal
from uuid import uuid4

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import playground
from .auth import current_user, session_token
from .config import settings
from .db import get_db
from .events import bus
from .gateway import (
    cipher,
    complete,
    generate_upstream_key,
    lock_mutation,
    revoke_upstream,
)
from .models import ApiKey, Approval, Asset, Budget, Department, Event, Team, User, now, uid
from .policy import (
    ASSET_ACTIONS,
    approval_resource,
    asset_resource,
    audit_resource,
    budget_resource,
    check_many,
    department_resource,
    explain,
    key_resource,
    permissions,
    platform_resource,
    principal,
    require,
    team_resource,
)
from .schemas import (
    AdminAssignment,
    AssetCreate,
    AssetEdit,
    BudgetChange,
    Completion,
    Decision,
    Delegation,
    DepartmentCreate,
    KeyRequest,
    Login,
)
from .serialize import dump

PLATFORM_ACTIONS = [
    "view_keys",
    "view_budgets",
    "view_organization",
    "view_audit",
    "view_policies",
    "create_department",
    "assign_cost_admin",
    "register_asset",
    "request_key",
]
# The dashboard shows the newest EVENT_PAGE_SIZE visible events, chosen from the newest
# EVENT_SCAN_LIMIT rows. Older history is not loaded into memory or sent to Cerbos.
EVENT_SCAN_LIMIT = 500
EVENT_PAGE_SIZE = 100
MAX_BODY_BYTES = 65536


@asynccontextmanager
async def lifespan(app):
    if len(settings().session_secret) < 32:
        raise RuntimeError("SESSION_SECRET must be at least 32 characters")
    cipher()  # Fail startup for invalid encryption configuration.
    worker = asyncio.create_task(bus.run())
    yield
    worker.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await worker


app = FastAPI(title="ai-cerbos", version="0.1.0", lifespan=lifespan)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    if request.url.path.startswith("/api/") and request.method not in ("GET", "HEAD", "OPTIONS"):
        if request.headers.get("X-Requested-With") != "ai-cerbos":
            return JSONResponse({"detail": "Missing same-origin request header"}, status_code=403)
        origin = request.headers.get("origin")
        if origin and origin != settings().allowed_origin:
            return JSONResponse({"detail": "Origin not allowed"}, status_code=403)
    # The size limit is enforced from Content-Length, so chunked bodies, which carry
    # no length, are refused outright instead of bypassing the check.
    if request.headers.get("transfer-encoding"):
        return JSONResponse({"detail": "Content-Length is required"}, status_code=411)
    try:
        content_length = int(request.headers.get("content-length", "0") or 0)
    except ValueError:
        return JSONResponse({"detail": "Invalid Content-Length"}, status_code=400)
    if content_length > MAX_BODY_BYTES:
        return JSONResponse({"detail": "Request exceeds 64 KiB"}, status_code=413)
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "same-origin"
    return response


def get_or_404(db, model, id):
    item = db.get(model, id)
    if not item:
        raise HTTPException(404, "Resource not found")
    return item


def micros(amount):
    return int(Decimal(str(amount)) * 1_000_000)


def asset_policy(db, asset):
    team = db.get(Team, asset.team_id) if asset.team_id else None
    return asset_resource(asset, team.cost_editor_ids if team else [])


def visible(db, user, cls, resource_fn, actions, rows=None):
    if rows is None:
        rows = db.scalars(select(cls)).all()
    decisions = check_many(user, [resource_fn(row) for row in rows], actions)
    return [
        (row, decisions.get(row.id, {})) for row in rows if decisions.get(row.id, {}).get("view")
    ]


def emit(db, type, user, obj, **detail):
    bus.emit(
        db,
        type,
        user.id,
        obj.id,
        getattr(obj, "department_id", ""),
        getattr(obj, "team_id", ""),
        **detail,
    )


def assert_budget(db, budget, amount):
    amount_micros = micros(amount)
    if amount_micros < budget.spent_micros + budget.reserved_micros:
        raise HTTPException(409, "Limit cannot be lower than spent plus reserved funds")
    parent_id = None
    if budget.scope == "department":
        parent_id = "organization"
    elif budget.scope == "team":
        parent_id = f"department:{budget.department_id}"
    elif budget.scope in ("asset", "key"):
        parent_id = (
            f"team:{budget.team_id}" if budget.team_id else f"department:{budget.department_id}"
        )
    parent = db.get(Budget, parent_id) if parent_id else None
    if parent_id and (not parent or amount_micros > parent.limit_micros):
        raise HTTPException(409, "Requested limit exceeds the parent budget")
    budget.limit_micros = amount_micros


@app.get("/api/health")
def health():
    return {"status": "ok", "demo_mode": settings().demo_mode}


@app.get("/api/demo-users")
def demo_users(db: Session = Depends(get_db)):
    if not settings().demo_mode:
        raise HTTPException(404, "Demo sign-in is disabled")
    return [dump(user) for user in db.scalars(select(User).where(User.active.is_(True))).all()]


@app.post("/api/session")
def login(body: Login, response: Response, db: Session = Depends(get_db)):
    if not settings().demo_mode:
        raise HTTPException(
            404, "Demo sign-in is disabled. Connect your identity provider for production."
        )
    user = get_or_404(db, User, body.user_id)
    if not user.active:
        raise HTTPException(403, "Account disabled")
    response.set_cookie(
        "cerbos_session",
        session_token(user),
        httponly=True,
        secure=settings().cookie_secure,
        samesite="strict",
        max_age=28800,
    )
    return dump(user)


@app.delete("/api/session")
def logout(response: Response):
    response.delete_cookie("cerbos_session")
    return {"ok": True}


@app.get("/api/state")
def state(user: User = Depends(current_user), db: Session = Depends(get_db)):
    platform = permissions(user, platform_resource(), PLATFORM_ACTIONS)
    # Reference tables are small and shared by every section below; load them once
    # instead of issuing a lookup per row.
    all_users = db.scalars(select(User)).all()
    users_by_id = {row.id: row for row in all_users}
    teams_by_id = {row.id: row for row in db.scalars(select(Team)).all()}
    departments_by_id = {row.id: row for row in db.scalars(select(Department)).all()}

    def name_of(table, id, fallback):
        row = table.get(id) if id else None
        return row.name if row else fallback

    def team_name(team_id):
        return name_of(teams_by_id, team_id, "Personal") if team_id else "Personal"

    def cost_editors(asset):
        team = teams_by_id.get(asset.team_id) if asset.team_id else None
        return team.cost_editor_ids if team else []

    asset_rows = [
        (asset, allowed)
        for asset, allowed in visible(
            db,
            user,
            Asset,
            lambda a: asset_resource(a, cost_editors(a)),
            ["view", *ASSET_ACTIONS[1:]],
        )
        if asset.status != "archived"
    ]
    asset_budgets = {
        row.id: row
        for row in db.scalars(
            select(Budget).where(Budget.id.in_([f"asset:{a.id}" for a, _ in asset_rows]))
        ).all()
    }
    # Catalog names are descriptive metadata. Budget values require a separate
    # budget permission or ownership; global visibility never exposes finances.
    # One batched Cerbos call covers every asset budget instead of one call per asset.
    budget_views = check_many(user, [budget_resource(b) for b in asset_budgets.values()], ["view"])
    assets = []
    for asset, allowed in asset_rows:
        budget = asset_budgets.get(f"asset:{asset.id}")
        budget_allowed = budget_views.get(budget.id, {}).get("view") if budget else False
        assets.append(
            {
                **dump(asset),
                "permissions": allowed,
                "budget": dump(budget)
                if budget
                and (budget_allowed or asset.owner_id == user.id or allowed.get("request_key"))
                else None,
                "owner_name": name_of(users_by_id, asset.owner_id, "Unknown"),
                "team_name": team_name(asset.team_id),
                "department_name": name_of(departments_by_id, asset.department_id, "Unknown"),
            }
        )
    approvals = [
        {
            **dump(row),
            "permissions": allowed,
            "requester_name": name_of(users_by_id, row.requester_id, "Unknown"),
            "department_name": name_of(departments_by_id, row.department_id, "Unknown"),
            "team_name": team_name(row.team_id),
        }
        for row, allowed in visible(
            db, user, Approval, approval_resource, ["view", "approve", "decline"]
        )
    ]
    key_rows = visible(db, user, ApiKey, key_resource, ["view", "claim", "revoke"])
    key_budgets = {
        row.id: row
        for row in db.scalars(
            select(Budget).where(Budget.id.in_([f"key:{k.id}" for k, _ in key_rows]))
        ).all()
    }
    keys = [
        {
            **dump(row),
            "permissions": allowed,
            "budget": dump(key_budgets[f"key:{row.id}"])
            if f"key:{row.id}" in key_budgets
            else None,
        }
        for row, allowed in key_rows
    ]
    budgets = (
        [
            {**dump(row), "permissions": allowed}
            for row, allowed in visible(db, user, Budget, budget_resource, ["view", "edit"])
        ]
        if platform.get("view_budgets")
        else []
    )
    teams = [
        {**dump(row), "permissions": allowed}
        for row, allowed in visible(
            db,
            user,
            Team,
            team_resource,
            ["view", "delegate_cost"],
        )
    ]
    departments = [
        dump(row) for row, _ in visible(db, user, Department, department_resource, ["view"])
    ]
    # The audit table grows with every gateway call. Authorize only the newest window
    # instead of sending the whole history to Cerbos on each dashboard load.
    recent_events = db.scalars(
        select(Event).order_by(Event.created_at.desc()).limit(EVENT_SCAN_LIMIT)
    ).all()
    events = [
        {**dump(row), "actor_name": name_of(users_by_id, row.actor_id, "System")}
        for row, _ in visible(
            db,
            user,
            Event,
            audit_resource,
            ["view"],
            rows=recent_events,
        )
    ]
    visible_team_ids = {team["id"] for team in teams}
    users = [
        dump(row)
        for row in all_users
        if platform.get("assign_cost_admin")
        or row.id == user.id
        or visible_team_ids.intersection(row.team_ids)
    ]
    return {
        "user": dump(user),
        "permissions": platform,
        "assets": assets,
        "approvals": sorted(approvals, key=lambda a: a["created_at"], reverse=True),
        "keys": keys,
        "budgets": budgets,
        "teams": teams,
        "departments": departments,
        "users": users,
        "events": events[:EVENT_PAGE_SIZE],
        "demo_mode": settings().demo_mode,
        "authorization": "Cerbos PDP",
        "model": "governed-demo",
    }


@app.get("/api/services")
def services(user: User = Depends(current_user)):
    result = {
        "api": "connected",
        "cerbos": "unavailable",
        "litellm": "unavailable",
        "provider": "deterministic demo",
    }
    for name, url in [
        ("cerbos", f"{settings().cerbos_url}/_cerbos/health"),
        ("litellm", f"{settings().litellm_url}/health/liveliness"),
    ]:
        try:
            response = httpx.get(url, timeout=3)
            if response.is_success:
                result[name] = "connected"
        except httpx.HTTPError:
            pass
    return result


@app.post("/api/assets", status_code=201)
def create_asset(
    body: AssetCreate, user: User = Depends(current_user), db: Session = Depends(get_db)
):
    lock_mutation(db)
    get_or_404(db, Department, body.department_id)
    if body.team_id:
        team = get_or_404(db, Team, body.team_id)
        if team.department_id != body.department_id:
            raise HTTPException(422, "Team must belong to the selected department")
    elif body.visibility == "team":
        raise HTTPException(422, "Team visibility requires a team")
    asset = Asset(
        id=uid(),
        owner_id=user.id,
        status="pending",
        model="governed-demo",
        **body.model_dump(exclude={"budget"}),
    )
    require(user, asset_policy(db, asset), "create")
    db.add(asset)
    db.flush()
    db.add(
        Budget(
            id=f"asset:{asset.id}",
            name=asset.name,
            scope="asset",
            department_id=asset.department_id,
            team_id=asset.team_id or "",
            limit_micros=0,
        )
    )
    db.add(
        Approval(
            kind="asset",
            title=f"Register {asset.name}",
            resource_id=asset.id,
            department_id=asset.department_id,
            team_id=asset.team_id,
            requester_id=user.id,
            payload={"version": 1, "budget": str(body.budget if asset.kind == "agent" else 0)},
            reason=asset.description,
        )
    )
    emit(db, "asset.submitted", user, asset, name=asset.name, kind=asset.kind)
    db.commit()
    return dump(asset)


@app.patch("/api/assets/{asset_id}")
def edit_asset(
    asset_id: str,
    body: AssetEdit,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    lock_mutation(db)
    asset = get_or_404(db, Asset, asset_id)
    require(user, asset_policy(db, asset), "edit")
    if asset.version != body.version:
        raise HTTPException(409, "Asset changed since you opened it. Refresh and try again.")
    if db.scalar(
        select(Approval).where(Approval.resource_id == asset.id, Approval.status == "pending")
    ):
        raise HTTPException(
            409, "Wait for the pending request to be reviewed before editing this asset"
        )
    for key, value in body.model_dump(exclude={"version"}).items():
        setattr(asset, key, value)
    asset.version += 1
    asset.status = "pending"
    budget = db.get(Budget, f"asset:{asset.id}")
    budget.name = asset.name
    db.add(
        Approval(
            kind="asset",
            title=f"Update {asset.name}",
            resource_id=asset.id,
            department_id=asset.department_id,
            team_id=asset.team_id,
            requester_id=user.id,
            payload={
                "version": asset.version,
                "budget": str(Decimal(budget.limit_micros) / 1_000_000),
            },
            reason="Asset metadata changed; reapproval is required before use.",
        )
    )
    emit(db, "asset.updated", user, asset, version=asset.version)
    db.commit()
    return dump(asset)


@app.delete("/api/assets/{asset_id}")
def delete_asset(asset_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    lock_mutation(db)
    asset = get_or_404(db, Asset, asset_id)
    require(user, asset_policy(db, asset), "delete")
    asset.status = "archived"
    for approval in db.scalars(
        select(Approval).where(Approval.resource_id == asset.id, Approval.status == "pending")
    ).all():
        approval.status, approval.review_note, approval.decided_at = (
            "cancelled",
            "Asset archived",
            now(),
        )
    revoked = []
    for key in db.scalars(select(ApiKey).where(ApiKey.asset_id == asset.id)).all():
        if key.status != "revoked":
            key.status = "revoked"
            revoked.append(key.id)
    emit(db, "asset.archived", user, asset, name=asset.name)
    db.commit()
    for key_id in revoked:
        revoke_upstream(key_id)
    return {"ok": True}


@app.post("/api/assets/{asset_id}/budget-requests", status_code=201)
def request_budget(
    asset_id: str,
    body: BudgetChange,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    lock_mutation(db)
    asset = get_or_404(db, Asset, asset_id)
    require(user, asset_policy(db, asset), "request_budget")
    if db.scalar(
        select(Approval).where(
            Approval.resource_id == asset.id,
            Approval.status == "pending",
            Approval.kind.in_(["asset", "budget"]),
        )
    ):
        raise HTTPException(409, "This asset already has a pending request")
    budget = db.get(Budget, f"asset:{asset.id}")
    # Validate without applying the proposed amount.
    previous = budget.limit_micros
    assert_budget(db, budget, body.amount)
    budget.limit_micros = previous
    approval = Approval(
        kind="budget",
        title=f"Budget for {asset.name}",
        resource_id=asset.id,
        department_id=asset.department_id,
        team_id=asset.team_id,
        requester_id=user.id,
        reason=body.reason,
        payload={"budget": str(body.amount), "previous_micros": previous},
    )
    db.add(approval)
    emit(db, "budget.change_requested", user, asset, requested_micros=micros(body.amount))
    db.commit()
    return {"ok": True}


@app.post("/api/key-requests", status_code=201)
def request_key(
    body: KeyRequest, user: User = Depends(current_user), db: Session = Depends(get_db)
):
    lock_mutation(db)
    asset = get_or_404(db, Asset, body.asset_id)
    require(user, asset_policy(db, asset), "request_key")
    budget = db.get(Budget, f"asset:{asset.id}")
    if body.budget <= 0 or micros(body.budget) > budget.limit_micros:
        raise HTTPException(
            422, "Key budget must be positive and no greater than the approved agent limit"
        )
    db.add(
        Approval(
            kind="key",
            title=body.name,
            resource_id=asset.id,
            department_id=asset.department_id,
            team_id=asset.team_id,
            requester_id=user.id,
            payload=body.model_dump(mode="json"),
            reason=body.reason,
        )
    )
    emit(db, "key.requested", user, asset, name=body.name, budget_micros=micros(body.budget))
    db.commit()
    return {"ok": True}


@app.post("/api/approvals/{approval_id}/decision")
def decide(
    approval_id: str,
    body: Decision,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    # Phase 1, unlocked: Cerbos checks and LiteLLM key issuance. Both are external
    # calls and must not hold the global mutation lock. Phase 2, locked: every row is
    # re-read and every state precondition is checked again before anything is written.
    approval = get_or_404(db, Approval, approval_id)
    require(user, approval_resource(approval), body.decision)
    asset = get_or_404(db, Asset, approval.resource_id)
    if asset.status == "archived":
        raise HTTPException(409, "This asset has been archived")
    issued = None
    if body.decision == "approve":
        requester = get_or_404(db, User, approval.requester_id)
        if not requester.active:
            raise HTTPException(409, "Requester account is no longer active")
        action = {"asset": "create", "budget": "request_budget", "key": "request_key"}[
            approval.kind
        ]
        require(requester, asset_policy(db, asset), action)
        if approval.kind == "key":
            issued = issue_key(db, approval, asset, requester, body)

    lock_mutation(db)
    db.expire_all()  # Re-read approval, asset, and budgets under the lock.
    if approval.status != "pending" or asset.status == "archived":
        if issued:
            revoke_upstream(issued.id)
        raise HTTPException(409, "This request was already decided or the asset was archived")
    if body.decision == "approve":
        if approval.kind in ("asset", "budget"):
            if approval.kind == "asset" and asset.version != approval.payload["version"]:
                raise HTTPException(409, "This approval refers to an outdated asset version")
            budget = get_or_404(db, Budget, f"asset:{asset.id}")
            assert_budget(db, budget, approval.payload["budget"])
            if approval.kind == "asset":
                asset.status = "active"
        else:
            key_limit = micros(issued.amount)
            agent_budget = get_or_404(db, Budget, f"asset:{asset.id}")
            if key_limit > agent_budget.limit_micros:
                revoke_upstream(issued.id)
                raise HTTPException(409, "Key limit exceeds the current approved agent budget")
            db.add(issued.key)
            db.add(
                Budget(
                    id=f"key:{issued.id}",
                    name=issued.key.name,
                    scope="key",
                    department_id=issued.key.department_id,
                    team_id=issued.key.team_id or "",
                    limit_micros=key_limit,
                )
            )
            emit(db, "key.issued", user, issued.key, owner_id=requester.id, budget_micros=key_limit)
    elif approval.kind == "asset":
        asset.status = "declined"
    approval.status = "approved" if body.decision == "approve" else "declined"
    approval.reviewer_id, approval.review_note, approval.decided_at = user.id, body.note, now()
    emit(db, f"approval.{approval.status}", user, approval, kind=approval.kind, note=body.note)
    db.commit()
    return {"ok": True}


class IssuedKey:
    def __init__(self, key: ApiKey, amount: Decimal):
        self.key, self.amount, self.id = key, amount, key.id


def issue_key(db, approval, asset, requester, body: Decision) -> IssuedKey:
    """Validate the approved limits and create the LiteLLM virtual key.

    Runs before the mutation lock. The returned key is not yet persisted; the caller
    stores it under the lock or deletes it upstream if the preconditions changed.
    LiteLLM aliases are globally unique; user-facing names are not. A fresh issuance
    ID also permits retry after an uncertain upstream outcome without colliding with
    an unclaimed orphaned key, and an orphaned key cannot be used at the public gateway.
    """
    requested = approval.payload
    amount = body.budget if body.budget is not None else Decimal(requested["budget"])
    rpm, tpm = body.rpm or requested["rpm"], body.tpm or requested["tpm"]
    if (
        amount <= 0
        or amount > Decimal(requested["budget"])
        or rpm > requested["rpm"]
        or tpm > requested["tpm"]
    ):
        raise HTTPException(
            422, "Approved limits must be positive and no higher than requested limits"
        )
    agent_budget = get_or_404(db, Budget, f"asset:{asset.id}")
    if micros(amount) > agent_budget.limit_micros:
        raise HTTPException(409, "Key limit exceeds the current approved agent budget")
    key = generate_upstream_key(
        name=requested["name"],
        owner=requester,
        asset=asset,
        amount=amount,
        rpm=rpm,
        tpm=tpm,
        days=requested["days"],
        extra_metadata={"approval_id": approval.id},
    )
    return IssuedKey(key, amount)


@app.patch("/api/budgets/{budget_id}")
def update_budget(
    budget_id: str,
    body: BudgetChange,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    lock_mutation(db)
    budget = get_or_404(db, Budget, budget_id)
    require(user, budget_resource(budget), "edit")
    before = budget.limit_micros
    assert_budget(db, budget, body.amount)
    emit(
        db,
        "budget.updated",
        user,
        budget,
        before_micros=before,
        after_micros=budget.limit_micros,
        reason=body.reason,
    )
    db.commit()
    return dump(budget)


@app.post("/api/keys/{key_id}/claim")
def claim_key(key_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    lock_mutation(db)
    key = get_or_404(db, ApiKey, key_id)
    require(user, key_resource(key), "claim")
    if key.claimed or key.status != "active" or key.expires_at <= now():
        raise HTTPException(409, "This key is already claimed or is no longer active")
    key.claimed = True
    secret = cipher().decrypt(key.encrypted_token.encode()).decode()
    emit(db, "key.claimed", user, key)
    db.commit()
    return {
        "key": secret,
        "base_url": f"{settings().allowed_origin}/v1",
        "model": "governed-demo",
    }


@app.post("/api/keys/{key_id}/revoke")
def revoke_key(key_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    lock_mutation(db)
    key = get_or_404(db, ApiKey, key_id)
    require(user, key_resource(key), "revoke")
    if key.status == "revoked":
        return {"ok": True}  # Idempotent: the upstream key is already gone.
    key.status = "revoked"
    # Local enforcement is immediate and remains effective if LiteLLM is offline.
    emit(db, "key.revoked", user, key)
    db.commit()
    revoke_upstream(key.id)
    return {"ok": True}


@app.put("/api/teams/{team_id}/delegations")
def delegate(
    team_id: str,
    body: Delegation,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    lock_mutation(db)
    team = get_or_404(db, Team, team_id)
    require(user, team_resource(team), "delegate_cost")
    target = get_or_404(db, User, body.user_id)
    if (
        team.id not in target.team_ids
        or not set(target.roles).intersection({"viewer", "developer"})
        or set(target.roles).intersection({"executive_admin", "cost_center_admin", "finance_admin"})
    ):
        raise HTTPException(422, "Delegation requires a viewer or developer in this team")
    ids = set(team.cost_editor_ids)
    ids.add(target.id) if body.grant else ids.discard(target.id)
    team.cost_editor_ids = sorted(ids)
    emit(
        db,
        "cost_access.granted" if body.grant else "cost_access.revoked",
        user,
        team,
        target_user_id=target.id,
    )
    db.commit()
    return {"ok": True}


@app.post("/api/departments", status_code=201)
def create_department(
    body: DepartmentCreate, user: User = Depends(current_user), db: Session = Depends(get_db)
):
    lock_mutation(db)
    require(user, platform_resource(), "create_department")
    if db.scalar(select(Department).where(Department.name == body.name)):
        raise HTTPException(409, "An operating unit already uses this name")
    department = Department(id=uid(), **body.model_dump())
    db.add(department)
    db.add(
        Budget(
            id=f"department:{department.id}",
            name=department.name,
            scope="department",
            department_id=department.id,
            limit_micros=0,
        )
    )
    emit(db, "department.created", user, department, name=department.name)
    db.commit()
    return dump(department)


@app.put("/api/departments/{department_id}/cost-admins")
def assign_admin(
    department_id: str,
    body: AdminAssignment,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    lock_mutation(db)
    require(user, platform_resource(), "assign_cost_admin")
    department = get_or_404(db, Department, department_id)
    target = get_or_404(db, User, body.user_id)
    # Dedicated finance identities prevent mixing approval authority with builders.
    if set(target.roles) - {"cost_center_admin"}:
        raise HTTPException(422, "Choose a dedicated cost-center administrator account")
    scopes = set(target.department_ids)
    scopes.add(department.id) if body.grant else scopes.discard(department.id)
    target.roles, target.department_ids = ["cost_center_admin"], sorted(scopes)
    emit(
        db,
        "cost_admin.assigned" if body.grant else "cost_admin.removed",
        user,
        department,
        target_user_id=target.id,
    )
    db.commit()
    return {"ok": True}


@app.get("/api/policy-check/{asset_id}")
def policy_check(asset_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    asset = get_or_404(db, Asset, asset_id)
    item = asset_policy(db, asset)
    require(user, item, "view")
    explanations = explain(principal(user), [item], ASSET_ACTIONS).get(item["id"], {})
    return {
        "engine": "Cerbos PDP",
        "policy_version": "default",
        "principal": {
            "id": user.id,
            "roles": user.roles,
            "team_ids": user.team_ids,
            "admin_team_ids": user.admin_team_ids,
            "department_ids": user.department_ids,
        },
        "resource": item,
        "decisions": {a: e["effect"] == "allow" for a, e in explanations.items()},
        "explanations": explanations,
    }


@app.post("/v1/chat/completions")
def chat_completions(
    body: Completion,
    authorization: str = Header(default=""),
    idempotency_key: str = Header(default=""),
):
    if not authorization.startswith("Bearer "):
        raise HTTPException(401, "Bearer API key required")
    if not idempotency_key or len(idempotency_key) > 100:
        raise HTTPException(422, "Provide an Idempotency-Key header (1–100 characters)")
    return complete(authorization[7:], body, idempotency_key)


@app.post("/api/keys/{key_id}/test")
def test_key(key_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    key = get_or_404(db, ApiKey, key_id)
    require(user, key_resource(key), "claim")
    token = cipher().decrypt(key.encrypted_token.encode()).decode()
    db.rollback()
    body = Completion(
        model="governed-demo",
        messages=[{"role": "user", "content": "Explain how this request is governed."}],
        max_tokens=128,
    )
    return complete(token, body, str(uuid4()))


# The Cerbos playground (demo mode only): explore, compare, edit policies, trace, reset.
app.include_router(playground.router)
