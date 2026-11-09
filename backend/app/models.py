from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


def uid():
    return str(uuid4())


def now():
    return datetime.now(UTC)


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    email: Mapped[str] = mapped_column(String(200), unique=True)
    roles: Mapped[list] = mapped_column(JSON, default=list)
    team_ids: Mapped[list] = mapped_column(JSON, default=list)
    admin_team_ids: Mapped[list] = mapped_column(JSON, default=list)
    department_ids: Mapped[list] = mapped_column(JSON, default=list)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Department(Base):
    __tablename__ = "departments"
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    description: Mapped[str] = mapped_column(Text, default="")


class Team(Base):
    __tablename__ = "teams"
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    name: Mapped[str] = mapped_column(String(120))
    department_id: Mapped[str] = mapped_column(ForeignKey("departments.id"))
    cost_editor_ids: Mapped[list] = mapped_column(JSON, default=list)


class Asset(Base):
    __tablename__ = "assets"
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(String(20))
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    team_id: Mapped[str | None] = mapped_column(ForeignKey("teams.id"), nullable=True)
    department_id: Mapped[str] = mapped_column(ForeignKey("departments.id"))
    visibility: Mapped[str] = mapped_column(String(16), default="team")
    status: Mapped[str] = mapped_column(String(20), default="pending")
    endpoint: Mapped[str] = mapped_column(String(500), default="")
    model: Mapped[str] = mapped_column(String(100), default="governed-demo")
    tags: Mapped[list] = mapped_column(JSON, default=list)
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Approval(Base):
    __tablename__ = "approvals"
    __table_args__ = (Index("ix_approvals_resource_status", "resource_id", "status"),)
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    kind: Mapped[str] = mapped_column(String(24))
    title: Mapped[str] = mapped_column(String(180))
    resource_id: Mapped[str] = mapped_column(String(64))
    department_id: Mapped[str] = mapped_column(ForeignKey("departments.id"))
    team_id: Mapped[str | None] = mapped_column(ForeignKey("teams.id"), nullable=True)
    requester_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    reviewer_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    reason: Mapped[str] = mapped_column(Text, default="")
    review_note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Budget(Base):
    __tablename__ = "budgets"
    __table_args__ = (
        CheckConstraint("limit_micros >= 0"),
        CheckConstraint("spent_micros >= 0"),
        CheckConstraint("reserved_micros >= 0"),
    )
    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    name: Mapped[str] = mapped_column(String(180))
    scope: Mapped[str] = mapped_column(String(20))
    department_id: Mapped[str] = mapped_column(String(64), default="")
    team_id: Mapped[str] = mapped_column(String(64), default="")
    limit_micros: Mapped[int] = mapped_column(BigInteger, default=0)
    spent_micros: Mapped[int] = mapped_column(BigInteger, default=0)
    reserved_micros: Mapped[int] = mapped_column(BigInteger, default=0)


class ApiKey(Base):
    __tablename__ = "api_keys"
    __table_args__ = (Index("ix_api_keys_asset_id", "asset_id"),)
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    name: Mapped[str] = mapped_column(String(120))
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    asset_id: Mapped[str] = mapped_column(ForeignKey("assets.id"))
    department_id: Mapped[str] = mapped_column(ForeignKey("departments.id"))
    team_id: Mapped[str | None] = mapped_column(ForeignKey("teams.id"), nullable=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    encrypted_token: Mapped[str] = mapped_column(Text)
    prefix: Mapped[str] = mapped_column(String(20))
    models: Mapped[list] = mapped_column(JSON)
    rpm: Mapped[int] = mapped_column(Integer)
    tpm: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default="active")
    claimed: Mapped[bool] = mapped_column(Boolean, default=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Reservation(Base):
    __tablename__ = "reservations"
    __table_args__ = (
        UniqueConstraint("key_id", "idempotency_key"),
        # Backs the per-key sliding-minute rate limit query in the ledger.
        Index("ix_reservations_key_created", "key_id", "created_at"),
    )
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    key_id: Mapped[str] = mapped_column(ForeignKey("api_keys.id"))
    idempotency_key: Mapped[str] = mapped_column(String(100))
    fingerprint: Mapped[str] = mapped_column(String(64))
    budget_ids: Mapped[list] = mapped_column(JSON)
    amount_micros: Mapped[int] = mapped_column(BigInteger)
    actual_micros: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    tokens: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default="reserved")
    response: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # "gateway" when the call came through the governed gateway, "direct" when a key holder
    # called LiteLLM themselves. Budgets apply to both (app/ledger.py).
    entry: Mapped[str] = mapped_column(String(16), default="gateway", server_default="gateway")
    model: Mapped[str] = mapped_column(String(100), default="", server_default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Event(Base):
    __tablename__ = "events"
    __table_args__ = (
        # Dashboard: newest events first.
        Index("ix_events_created_at", "created_at"),
        # Outbox poll: only undelivered, unparked rows.
        Index(
            "ix_events_outbox",
            "created_at",
            postgresql_where=text("delivered_at IS NULL AND failed_at IS NULL"),
        ),
    )
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    type: Mapped[str] = mapped_column(String(100))
    actor_id: Mapped[str] = mapped_column(String(64))
    department_id: Mapped[str] = mapped_column(String(64), default="")
    team_id: Mapped[str] = mapped_column(String(64), default="")
    resource_id: Mapped[str] = mapped_column(String(100))
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
