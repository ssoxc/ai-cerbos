"""A transactional outbox plus an at-least-once in-process EventBus.

Every business mutation inserts its event in the same database transaction.
Subscribers must be idempotent: a process can crash after delivery but before ack.
"""

import asyncio
import logging
from collections import defaultdict

from sqlalchemy import select

from .db import SessionLocal
from .models import Event, now

log = logging.getLogger("ai_cerbos.events")
MAX_ATTEMPTS = 5


class EventBus:
    def __init__(self):
        self.handlers = defaultdict(list)

    def subscribe(self, topic, handler):
        self.handlers[topic].append(handler)

    def emit(self, db, type, actor_id, resource_id, department_id="", team_id="", **detail):
        event = Event(
            type=type,
            actor_id=actor_id,
            resource_id=resource_id,
            department_id=department_id,
            team_id=team_id or "",
            detail=detail,
        )
        db.add(event)

    def dispatch_once(self):
        with SessionLocal.begin() as db:
            events = db.scalars(
                select(Event)
                .where(Event.delivered_at.is_(None), Event.failed_at.is_(None))
                .order_by(Event.created_at)
                .limit(50)
                .with_for_update(skip_locked=True)
            ).all()
            for event in events:
                # Each event runs in its own savepoint so one failing handler cannot
                # roll back, or indefinitely block, the rest of the batch.
                try:
                    with db.begin_nested():
                        for handler in [*self.handlers["*"], *self.handlers[event.type]]:
                            handler(event)
                except Exception:
                    event.attempts += 1
                    if event.attempts >= MAX_ATTEMPTS:
                        event.failed_at = now()
                        log.exception(
                            "event=%s type=%s parked after %d failed attempts",
                            event.id,
                            event.type,
                            event.attempts,
                        )
                    else:
                        log.exception(
                            "event=%s type=%s handler failed; attempt %d will retry",
                            event.id,
                            event.type,
                            event.attempts,
                        )
                    continue
                event.delivered_at = now()

    async def run(self):
        while True:
            try:
                await asyncio.to_thread(self.dispatch_once)
            except Exception:
                log.exception("Event delivery failed; unacknowledged events will retry")
            await asyncio.sleep(2)


bus = EventBus()
bus.subscribe(
    "*",
    lambda event: log.info("event=%s type=%s resource=%s", event.id, event.type, event.resource_id),
)
