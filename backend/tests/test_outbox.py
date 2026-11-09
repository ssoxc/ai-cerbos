from sqlalchemy import select

from app.db import SessionLocal
from app.events import MAX_ATTEMPTS, EventBus
from app.models import Event


def pending_events(db):
    return db.scalars(
        select(Event).where(Event.delivered_at.is_(None), Event.failed_at.is_(None))
    ).all()


def test_failing_handler_is_parked_without_blocking_other_events(db):
    with SessionLocal.begin() as session:
        session.execute(Event.__table__.update().values(delivered_at=Event.created_at))
        session.add(Event(type="poison", actor_id="alex", resource_id="x"))
        session.add(Event(type="healthy", actor_id="alex", resource_id="y"))
    bus = EventBus()
    delivered = []
    bus.subscribe("healthy", delivered.append)

    def explode(event):
        raise RuntimeError("handler bug")

    bus.subscribe("poison", explode)
    for _ in range(MAX_ATTEMPTS):
        bus.dispatch_once()
    assert len(delivered) == 1
    poison = db.scalar(select(Event).where(Event.type == "poison"))
    assert poison.attempts == MAX_ATTEMPTS
    assert poison.failed_at is not None and poison.delivered_at is None
    assert pending_events(db) == []
    bus.dispatch_once()
    db.expire_all()
    assert db.scalar(select(Event).where(Event.type == "poison")).attempts == MAX_ATTEMPTS


def test_chunked_request_bodies_are_refused(client):
    response = client.post(
        "/api/session",
        headers={"Transfer-Encoding": "chunked"},
        content=b'{"user_id": "alex"}',
    )
    assert response.status_code == 411
