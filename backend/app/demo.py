"""Demo-only operations: restore the sample workspace, and issue the demo API keys.

python -m app.demo reset   # sample data and shipped policies, as on first start
"""

import logging
import sys

from sqlalchemy import select, text

from . import policy_store
from .db import Base, SessionLocal, engine
from .events import bus
from .gateway import generate_upstream_key, lock_mutation, revoke_upstream
from .models import ApiKey, Asset, Budget, User
from .seed import seed

log = logging.getLogger("ai_cerbos.demo")

# One key per side of the premium-model policy: a Platform-team key and an Agents-team key.
DEMO_KEYS = [
    {
        "owner": "alex",
        "asset": "atlas",
        "team": "Platform Engineering",
        "name": "Demo key · Alex · Platform Engineering",
    },
    {
        "owner": "sam",
        "asset": "insights",
        "team": "Agents & Automation",
        "name": "Demo key · Sam · Agents & Automation",
    },
    {
        "owner": "riley",
        "asset": "people-assistant",
        "team": "People Operations",
        "name": "Demo key · Riley · People Operations",
    },
]
DEMO_KEY_BUDGET_USD = 5
DEMO_KEY_MICROS = DEMO_KEY_BUDGET_USD * 1_000_000


def demo_keys(db):
    """The active demo keys, by owner."""
    names = {spec["name"] for spec in DEMO_KEYS}
    keys = db.scalars(select(ApiKey).where(ApiKey.name.in_(names), ApiKey.status == "active"))
    return {key.owner_id: key for key in keys}


DEMO_KEY_LOCK = 918273


def ensure_demo_keys(actor_id: str):
    """Issue any missing demo key through the normal LiteLLM path. Idempotent.

    A session-level advisory lock serialises concurrent callers (several playground panels
    load at once), so each demo key is issued exactly once.
    """
    with SessionLocal() as guard:
        guard.execute(text("SELECT pg_advisory_lock(:id)"), {"id": DEMO_KEY_LOCK})
        try:
            return _ensure_demo_keys(actor_id)
        finally:
            guard.execute(text("SELECT pg_advisory_unlock(:id)"), {"id": DEMO_KEY_LOCK})


def _ensure_demo_keys(actor_id: str):
    with SessionLocal() as db:
        existing = demo_keys(db)
        missing = [spec for spec in DEMO_KEYS if spec["owner"] not in existing]
        planned = []
        for spec in missing:
            owner, asset = db.get(User, spec["owner"]), db.get(Asset, spec["asset"])
            if not owner or not asset or asset.status != "active":
                continue
            # External call first, outside any lock, like a normal approval.
            key = generate_upstream_key(
                name=spec["name"],
                owner=owner,
                asset=asset,
                amount=DEMO_KEY_BUDGET_USD,
                rpm=60,
                tpm=100_000,
                days=30,
                extra_metadata={"demo": True},
            )
            planned.append(key)
        db.rollback()
        if not planned:
            return demo_keys(db)
        lock_mutation(db)
        for key in planned:
            db.add(key)
            db.add(
                Budget(
                    id=f"key:{key.id}",
                    name=key.name,
                    scope="key",
                    department_id=key.department_id,
                    team_id=key.team_id or "",
                    limit_micros=DEMO_KEY_MICROS,
                )
            )
            bus.emit(
                db,
                "demo.key_issued",
                actor_id,
                key.id,
                key.department_id,
                key.team_id or "",
                owner_id=key.owner_id,
                name=key.name,
            )
        db.commit()
        return demo_keys(db)


def reset_workspace():
    """Delete issued keys upstream, restore sample data and the shipped policies."""
    with SessionLocal() as db:
        key_ids = list(db.scalars(select(ApiKey.id)))
    for key_id in key_ids:
        revoke_upstream(key_id)
    with engine.begin() as connection:
        names = ", ".join(table.name for table in Base.metadata.sorted_tables)
        connection.execute(text(f"TRUNCATE {names} CASCADE"))
    seed()
    policy_store.reset()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    if sys.argv[1:] == ["reset"]:
        reset_workspace()
        print("Demo workspace reset: sample data and shipped Cerbos policies restored.")
    else:
        sys.exit("usage: python -m app.demo reset")
